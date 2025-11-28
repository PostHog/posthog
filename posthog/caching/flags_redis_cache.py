import logging
from typing import Any, Optional

from django.conf import settings
from django.core.cache import cache, caches

from posthog.exceptions_capture import capture_exception

logger = logging.getLogger(__name__)

FLAGS_DEDICATED_CACHE_ALIAS = "flags_dedicated"


def write_flags_to_cache(key: str, value: Any, timeout: Optional[int] = None) -> None:
    """Write feature flags to the appropriate cache(s).

    - FLAGS_REDIS_URL not set: writes to shared cache only
    - FLAGS_REDIS_URL set: dual-writes to both shared and dedicated
      (Django reads from shared, Rust service reads from dedicated)
    """
    has_dedicated_cache = FLAGS_DEDICATED_CACHE_ALIAS in settings.CACHES

    try:
        # Always write to shared cache. If it fails, let the caller handle the error.
        cache.set(key, value, timeout)

        if has_dedicated_cache:
            try:
                dedicated_cache = caches[FLAGS_DEDICATED_CACHE_ALIAS]
                dedicated_cache.set(key, value, timeout)
            except Exception as e:
                logger.warning(
                    "Dedicated cache write failed",
                    extra={"key": key},
                    exc_info=True,
                )
                capture_exception(e)
    except Exception as e:
        logger.exception("Failed to write to cache", extra={"key": key})
        capture_exception(e)
