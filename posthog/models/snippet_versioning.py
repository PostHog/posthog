import os
import re
import json
import time
from typing import NotRequired, Optional, TypedDict

from django.conf import settings
from django.core.cache import cache

import structlog

from posthog.storage import object_storage
from posthog.storage.object_storage import ObjectStorageError

logger = structlog.get_logger(__name__)

# Disk fallback: the array.js shipped with the current deploy
_disk_js_content: Optional[str] = None

DEFAULT_SNIPPET_VERSION = "1"
S3_VERSIONS_KEY = "versions.json"

REDIS_JS_CONTENT_TTL = 60 * 60 * 24 * 30  # 30 days — version content is immutable
REDIS_JS_KEY_PREFIX = "posthog_js_content"
REDIS_POINTER_MAP_KEY = "posthog_js_latest_pointers"

# In-process cache for pointer map
_pointer_map_cache: Optional[dict] = None
_pointer_map_cache_time: float = 0
POINTER_MAP_IN_PROCESS_TTL = 60  # seconds

# Matches exact version like "1.358.0"
_EXACT_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")


class VersionEntry(TypedDict):
    version: str
    timestamp: str
    yanked: NotRequired[bool | None]


def _parse_version(version: str) -> tuple[int, int, int]:
    parts = version.split(".")
    return (int(parts[0]), int(parts[1]), int(parts[2]))


def compute_pointer_map(entries: list[VersionEntry]) -> dict[str, str]:
    """
    Compute the version pointer map from a versions manifest.

    For each non-yanked version, tracks the highest version for each
    major ("1") and minor ("1.358") pointer.
    """
    pointers: dict[str, str] = {}
    best: dict[str, tuple[int, int, int]] = {}

    for entry in entries:
        if entry.get("yanked", False):
            continue
        version = entry["version"]
        parsed = _parse_version(version)
        major, minor, _patch = parsed

        for pointer in [str(major), f"{major}.{minor}"]:
            if pointer not in best or parsed > best[pointer]:
                best[pointer] = parsed
                pointers[pointer] = version

    return pointers


def _get_disk_js_content() -> str:
    """Load array.js from disk (same as today's behavior). Cached in-process."""
    global _disk_js_content
    if _disk_js_content is None:
        with open(os.path.join(settings.BASE_DIR, "frontend/dist/array.js")) as f:
            _disk_js_content = f.read()
    return _disk_js_content


def _get_redis_key(version: str) -> str:
    return f"{REDIS_JS_KEY_PREFIX}:{version}"


def get_js_content(requested_version: Optional[str] = None) -> str:
    """
    Get posthog-js array.js content, resolving the version first.

    Accepts a raw version pin (major, minor, or exact) and resolves it
    to a concrete version. Falls back to disk if versioning is not
    configured or the version can't be resolved.

    Fallback chain for resolved versions:
    1. Redis (version-keyed, immutable)
    2. S3 bucket (v{version}/array.js)
    3. Disk (frontend/dist/array.js from current deploy)
    """
    version = resolve_version(requested_version)

    if version is None:
        return _get_disk_js_content()

    if not _EXACT_VERSION_RE.match(version):
        logger.warning("Invalid resolved version, falling back to disk", version=version)
        return _get_disk_js_content()

    # 1. Try Redis
    redis_key = _get_redis_key(version)
    cached = cache.get(redis_key)
    if cached is not None:
        return cached

    # 2. Try S3
    try:
        s3_key = f"v{version}/array.js"
        content = object_storage.read(s3_key, bucket=settings.POSTHOG_JS_S3_BUCKET, missing_ok=True)
        if content is not None:
            cache.set(redis_key, content, REDIS_JS_CONTENT_TTL)
            return content
    except ObjectStorageError:
        logger.exception("Failed to read JS content from S3", version=version)

    # 3. Disk fallback
    logger.warning("Falling back to disk JS content", version=version)
    return _get_disk_js_content()


def _get_pointer_map() -> Optional[dict]:
    """Get pointer map from in-process cache -> Redis."""
    global _pointer_map_cache, _pointer_map_cache_time

    now = time.time()
    if _pointer_map_cache is not None and (now - _pointer_map_cache_time) < POINTER_MAP_IN_PROCESS_TTL:
        return _pointer_map_cache

    raw = cache.get(REDIS_POINTER_MAP_KEY)
    if raw is not None:
        _pointer_map_cache = json.loads(raw) if isinstance(raw, str) else raw
        _pointer_map_cache_time = now
        return _pointer_map_cache

    return None


def validate_version_artifacts(version: str) -> bool:
    """Check that the required artifacts exist in S3 for a given version."""
    if not settings.POSTHOG_JS_S3_BUCKET:
        return False
    try:
        content = object_storage.read(
            f"v{version}/array.js",
            bucket=settings.POSTHOG_JS_S3_BUCKET,
            missing_ok=True,
        )
        return content is not None
    except ObjectStorageError:
        logger.exception("Failed to validate artifacts", version=version)
        return False


def resolve_version(requested_version: Optional[str]) -> Optional[str]:
    """
    Resolve a requested version to a concrete version string.

    - None -> defaults to "1" (major version)
    - "1.358.0" -> exact version (returned as-is)
    - "1" -> latest 1.x.x via pointers
    - "1.358" -> latest 1.358.x via pointers
    """
    if not settings.POSTHOG_JS_S3_BUCKET:
        return None

    if requested_version is not None and _EXACT_VERSION_RE.match(requested_version):
        return requested_version

    pointers = _get_pointer_map()
    if pointers is None:
        return None

    if requested_version is None:
        requested_version = DEFAULT_SNIPPET_VERSION

    return pointers.get(requested_version)
