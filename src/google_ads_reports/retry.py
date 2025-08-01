"""
Retry decorator for handling transient errors.
"""
import logging
import random
import time
from functools import wraps
from typing import Any, Callable

from google.ads.googleads.errors import GoogleAdsException

from .exceptions import APIError


def retry_on_api_error(
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    backoff_factor: float = 2.0,
    jitter: bool = True
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """
    Decorator to retry function calls on transient API errors.

    Args:
        max_attempts: Maximum number of retry attempts
        base_delay: Base delay between retries in seconds
        max_delay: Maximum delay between retries in seconds
        backoff_factor: Exponential backoff factor
        jitter: Add random jitter to prevent thundering herd

    Returns:
        Decorated function with retry logic
    """
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exception = None

            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)

                except GoogleAdsException as e:
                    last_exception = e

                    # Check if this is a retryable error
                    if not _is_retryable_error(e):
                        logging.warning(f"Non-retryable error in {func.__name__}: {e}")
                        raise APIError(
                            f"Google Ads API error in {func.__name__}",
                            original_error=e,
                            attempt=attempt + 1
                        ) from e

                    # Don't retry on the last attempt
                    if attempt == max_attempts - 1:
                        break

                    # Calculate delay with exponential backoff
                    delay = min(base_delay * (backoff_factor ** attempt), max_delay)

                    # Add jitter to prevent thundering herd
                    if jitter:
                        delay = delay * (0.5 + random.random() * 0.5)

                    logging.warning(
                        f"Attempt {attempt + 1}/{max_attempts} failed for {func.__name__}: {e}. "
                        f"Retrying in {delay:.1f} seconds..."
                    )

                    time.sleep(delay)

                except Exception as e:
                    # Non-Google Ads exceptions are not retried
                    logging.error(f"Unexpected error in {func.__name__}: {e}")
                    raise

            # All retries exhausted
            logging.error(f"All {max_attempts} attempts failed for {func.__name__}")
            raise APIError(
                f"Max retries exceeded for {func.__name__}",
                original_error=last_exception,
                max_attempts=max_attempts
            ) from last_exception

        return wrapper
    return decorator


def _is_retryable_error(error: GoogleAdsException) -> bool:
    """
    Determine if a GoogleAdsException is retryable.

    Args:
        error: The GoogleAdsException to check

    Returns:
        bool: True if the error should be retried
    """
    # Conservative approach - only retry on obvious transient errors
    retryable_error_codes = {
        'INTERNAL_ERROR',
        'QUOTA_ERROR',
        'RATE_EXCEEDED',
        'CONCURRENT_MODIFICATION',
        'PARTIAL_FAILURE_ERROR'
    }

    retryable_messages = [
        'internal error',
        'rate exceeded',
        'quota exceeded',
        'timeout',
        'temporary failure',
        'service unavailable'
    ]

    # Check error code
    if hasattr(error, 'error') and hasattr(error.error, 'error_code'):
        error_code = str(error.error.error_code)
        if any(code in error_code.upper() for code in retryable_error_codes):
            return True

    # Check error message
    error_message = str(error).lower()
    if any(msg in error_message for msg in retryable_messages):
        return True

    return False
