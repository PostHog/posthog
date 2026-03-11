import os
import re
import json
import time
from typing import Optional

from django.conf import settings
from django.core.cache import cache

import structlog

from posthog.storage import object_storage
from posthog.storage.object_storage import ObjectStorageError

logger = structlog.get_logger(__name__)

# Disk fallback: the array.js shipped with the current deploy
_disk_js_content: Optional[str] = None

REDIS_JS_CONTENT_TTL = 60 * 60 * 24 * 30  # 30 days — version content is immutable
REDIS_JS_KEY_PREFIX = "posthog_js_content"
REDIS_LATEST_KEY = "posthog_js_latest_pointers"

# In-process cache for latest pointers
_latest_pointers_cache: Optional[dict] = None
_latest_pointers_cache_time: float = 0
LATEST_POINTERS_IN_PROCESS_TTL = 60  # seconds

# Matches exact version like "1.358.0"
_EXACT_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")


def _get_disk_js_content() -> str:
    """Load array.js from disk (same as today's behavior). Cached in-process."""
    global _disk_js_content
    if _disk_js_content is None:
        with open(os.path.join(settings.BASE_DIR, "frontend/dist/array.js")) as f:
            _disk_js_content = f.read()
    return _disk_js_content


def _get_redis_key(version: str) -> str:
    return f"{REDIS_JS_KEY_PREFIX}:{version}"


def get_js_content(version: str) -> str:
    """
    Get posthog-js array.js content for a specific version.

    Fallback chain:
    1. Redis (version-keyed, immutable)
    2. S3 bucket (posthog-js/v{version}/array.js)
    3. Disk (frontend/dist/array.js from current deploy)
    """
    if not settings.POSTHOG_JS_S3_BUCKET:
        return _get_disk_js_content()

    # 1. Try Redis
    redis_key = _get_redis_key(version)
    cached = cache.get(redis_key)
    if cached is not None:
        return cached

    # 2. Try S3
    try:
        s3_key = f"posthog-js/v{version}/array.js"
        content = object_storage.read(s3_key, bucket=settings.POSTHOG_JS_S3_BUCKET, missing_ok=True)
        if content is not None:
            cache.set(redis_key, content, REDIS_JS_CONTENT_TTL)
            return content
    except ObjectStorageError:
        logger.exception("Failed to read JS content from S3", version=version)

    # 3. Disk fallback
    logger.warning("Falling back to disk JS content", version=version)
    return _get_disk_js_content()


def _get_latest_pointers() -> Optional[dict]:
    """Get latest.json pointers from in-process cache -> Redis."""
    global _latest_pointers_cache, _latest_pointers_cache_time

    now = time.time()
    if _latest_pointers_cache is not None and (now - _latest_pointers_cache_time) < LATEST_POINTERS_IN_PROCESS_TTL:
        return _latest_pointers_cache

    raw = cache.get(REDIS_LATEST_KEY)
    if raw is not None:
        _latest_pointers_cache = json.loads(raw) if isinstance(raw, str) else raw
        _latest_pointers_cache_time = now
        return _latest_pointers_cache

    return None


def resolve_latest() -> Optional[str]:
    """Resolve the 'latest' pointer to a concrete version string."""
    if not settings.POSTHOG_JS_S3_BUCKET:
        return None
    pointers = _get_latest_pointers()
    if pointers is None:
        return None
    return pointers.get("latest")


def validate_version_artifacts(version: str) -> bool:
    """Check that the required artifacts exist in S3 for a given version."""
    if not settings.POSTHOG_JS_S3_BUCKET:
        return False
    try:
        content = object_storage.read(
            f"posthog-js/v{version}/array.js",
            bucket=settings.POSTHOG_JS_S3_BUCKET,
            missing_ok=True,
        )
        return content is not None
    except ObjectStorageError:
        logger.exception("Failed to validate artifacts", version=version)
        return False


def resolve_version(pin: Optional[str]) -> Optional[str]:
    """
    Resolve a version pin to a concrete version string.

    - None -> defaults to "1" (major pin)
    - "1.358.0" -> exact version (returned as-is)
    - "1" -> latest 1.x.x via pointers
    - "1.358" -> latest 1.358.x via pointers
    """
    if not settings.POSTHOG_JS_S3_BUCKET:
        return None

    if pin is not None and _EXACT_VERSION_RE.match(pin):
        return pin

    pointers = _get_latest_pointers()
    if pointers is None:
        return None

    # Default to major pin "1" when no pin is set
    if pin is None:
        pin = "1"

    return pointers.get(pin)
