import os
import re
import json
import time
from dataclasses import dataclass
from typing import NotRequired, Optional, TypedDict

from django.conf import settings
from django.core.cache import cache

import structlog

from posthog.exceptions_capture import capture_exception
from posthog.storage import object_storage
from posthog.storage.object_storage import ObjectStorageError

logger = structlog.get_logger(__name__)

# Disk fallback: the array.js shipped with the current deploy
_disk_js_content: Optional[str] = None

DEFAULT_SNIPPET_VERSION = "1"
S3_VERSIONS_KEY = "versions.json"
S3_JS_ENTRY_POINT = "array.js"


def array_js_path(version: str) -> str:
    return f"{version}/{S3_JS_ENTRY_POINT}"


REDIS_JS_CONTENT_TTL = 60 * 60 * 24 * 30  # 30 days — version content is immutable
REDIS_JS_KEY_PREFIX = "js_snippet"
REDIS_POINTER_MAP_KEY = "js_snippet:manifest"

# Matches exact version like "1.358.0"
_EXACT_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")


class VersionEntry(TypedDict):
    version: str
    timestamp: str
    yanked: NotRequired[bool | None]


class VersionManifest(TypedDict):
    """Represents the version manifest stored in Redis"""

    versions: list[str]
    pointers: dict[str, str]


MANIFEST_IN_PROCESS_TTL = 60  # seconds


@dataclass
class CachedManifest:
    """In-memory representation of a version manifest, with a set for O(1) exact version lookups."""

    versions: frozenset[str]
    pointers: dict[str, str]
    cached_at: float

    @staticmethod
    def from_json(raw: str) -> "CachedManifest":
        data = json.loads(raw) if isinstance(raw, str) else raw
        return CachedManifest(
            versions=frozenset(data["versions"]),
            pointers=data["pointers"],
            cached_at=time.time(),
        )

    @property
    def is_fresh(self) -> bool:
        return (time.time() - self.cached_at) < MANIFEST_IN_PROCESS_TTL


# In-process cache
_cached_manifest: Optional[CachedManifest] = None


def _parse_version(version: str) -> tuple[int, int, int]:
    parts = version.split(".")
    return (int(parts[0]), int(parts[1]), int(parts[2]))


def compute_version_manifest(entries: list[VersionEntry]) -> VersionManifest:
    """
    Compute a version manifest from a list of version entries.

    Returns all non-yanked versions and a pointer map that tracks the
    highest version for each major ("1") and minor ("1.358") alias.
    """
    versions: list[str] = []
    pointers: dict[str, str] = {}
    best: dict[str, tuple[int, int, int]] = {}

    for entry in entries:
        if entry.get("yanked", False):
            continue
        version = entry["version"]
        versions.append(version)

        # Only strict semver versions (e.g. "1.358.0") participate in pointer
        # computation. Pre-release tags like "1.358.0-dev" are included in
        # the versions list so teams can pin to them, but they don't become
        # pointer targets.
        if not _EXACT_VERSION_RE.match(version):
            continue
        parsed = _parse_version(version)
        major, minor, _patch = parsed

        for pointer in [str(major), f"{major}.{minor}"]:
            if pointer not in best or parsed > best[pointer]:
                best[pointer] = parsed
                pointers[pointer] = version

    return {"versions": versions, "pointers": pointers}


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
    2. S3 bucket ({version}/array.js)
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
        s3_key = array_js_path(version)
        content = object_storage.read(s3_key, bucket=settings.POSTHOG_JS_S3_BUCKET, missing_ok=True)
        if content is not None:
            cache.set(redis_key, content, REDIS_JS_CONTENT_TTL)
            return content
    except ObjectStorageError:
        logger.exception("Failed to read JS content from S3", version=version)

    # 3. Disk fallback
    logger.warning("Falling back to disk JS content", version=version)
    return _get_disk_js_content()


def _get_manifest() -> Optional[CachedManifest]:
    """Get version manifest from in-process cache -> Redis."""
    global _cached_manifest

    if _cached_manifest is not None and _cached_manifest.is_fresh:
        return _cached_manifest

    raw = cache.get(REDIS_POINTER_MAP_KEY)
    if raw is not None:
        try:
            _cached_manifest = CachedManifest.from_json(raw)
            return _cached_manifest
        except Exception as e:
            capture_exception(
                e, additional_properties={"tag": "snippet_versioning", "redis_key": REDIS_POINTER_MAP_KEY}
            )
    elif settings.POSTHOG_JS_S3_BUCKET:
        capture_exception(
            Exception("Version manifest not found in Redis"),
            additional_properties={"tag": "snippet_versioning", "redis_key": REDIS_POINTER_MAP_KEY},
        )

    return None


def validate_version_artifacts(version: str) -> bool:
    """Check that the required artifacts exist in S3 for a given version."""
    if not settings.POSTHOG_JS_S3_BUCKET:
        return False
    try:
        content = object_storage.read(
            array_js_path(version),
            bucket=settings.POSTHOG_JS_S3_BUCKET,
            missing_ok=True,
        )
        return content is not None
    except ObjectStorageError:
        logger.exception("Failed to validate artifacts", version=version)
        return False


class ManifestSyncError(Exception):
    """Raised when syncing the version manifest from S3 fails."""

    pass


def changed_pointers(before: dict[str, str], after: dict[str, str]) -> set[str]:
    """Return pointers whose resolved version changed, was added, or was removed."""
    all_keys = set(before) | set(after)
    return {key for key in all_keys if before.get(key) != after.get(key)}


def _purge_changed_pointers(before: dict[str, str], after: dict[str, str]) -> None:
    """Purge CDN cache for any pointers that changed between two manifests."""
    from posthog.models.remote_config import RemoteConfig

    changed = changed_pointers(before, after)
    for pointer in changed:
        # NOTE: each of these calls is another HTTP request to the CDN. in practice,
        # .      the number of changed pointers should be very small, but this is
        #       technically unbounded
        RemoteConfig.purge_cdn_by_tag(f"posthog-js-{pointer}")
    if changed:
        logger.info("Purged CDN for changed pointers", pointers=sorted(changed))


def sync_manifest_from_s3() -> VersionManifest:
    """
    Read versions.json from S3, compute manifest, validate major pins, write to Redis,
    and purge CDN cache for any changed pointers.

    Raises ManifestSyncError if anything goes wrong.
    """
    # Snapshot old pointers before overwriting
    old_raw = cache.get(REDIS_POINTER_MAP_KEY)
    old_pointers: dict[str, str] = {}
    if old_raw:
        try:
            old_pointers = json.loads(old_raw).get("pointers", {})
        except (json.JSONDecodeError, TypeError) as e:
            capture_exception(
                e, additional_properties={"tag": "snippet_versioning", "redis_key": REDIS_POINTER_MAP_KEY}
            )

    raw = object_storage.read(
        S3_VERSIONS_KEY,
        bucket=settings.POSTHOG_JS_S3_BUCKET,
        missing_ok=True,
    )
    if raw is None:
        raise ManifestSyncError("versions.json not found in S3")

    entries = json.loads(raw)
    if not entries:
        raise ManifestSyncError("versions.json is empty")

    manifest = compute_version_manifest(entries)

    # Validate that major pin targets have artifacts, falling back to the
    # next-highest version if the top one is missing (e.g. broken publish)
    #
    # In practice, this shouldn't ever iterate more than once per major version.
    semver_versions = [v for v in manifest["versions"] if _EXACT_VERSION_RE.match(v)]
    sorted_versions = sorted(semver_versions, key=_parse_version, reverse=True)
    major_pins = {pin: ver for pin, ver in manifest["pointers"].items() if "." not in pin}
    for pin, version in major_pins.items():
        if validate_version_artifacts(version):
            continue
        major = int(pin)
        missing_artifacts: list[str] = []
        for candidate in sorted_versions:
            if _parse_version(candidate)[0] != major:
                continue
            if validate_version_artifacts(candidate):
                logger.warning("Major pin %s: %s missing artifacts, fell back to %s", pin, version, candidate)
                manifest["pointers"][pin] = candidate
                break
            missing_artifacts.append(candidate)
        else:
            raise ManifestSyncError(f"No viable version for major pin {pin}")
        if missing_artifacts:
            capture_exception(
                Exception(f"Major pin {pin}: {len(missing_artifacts)} version(s) missing artifacts"),
                additional_properties={
                    "tag": "snippet_versioning",
                    "missing_versions": missing_artifacts,
                    "fell_back_to": manifest["pointers"][pin],
                },
            )

    cache.set(REDIS_POINTER_MAP_KEY, json.dumps(manifest), timeout=None)
    _purge_changed_pointers(old_pointers, manifest["pointers"])
    return manifest


def resolve_version(requested_version: Optional[str]) -> Optional[str]:
    """
    Resolve a requested version to a concrete version string.

    - None -> defaults to "1" (major version)
    - "1.358.0" -> exact version (verified against known versions)
    - "1" -> latest 1.x.x via pointers
    - "1.358" -> latest 1.358.x via pointers

    Returns None if the version can't be resolved or isn't known.
    """
    if not settings.POSTHOG_JS_S3_BUCKET:
        return None

    manifest = _get_manifest()
    if manifest is None:
        return None

    if requested_version is None:
        requested_version = DEFAULT_SNIPPET_VERSION

    # Alias lookup (major/minor pointers)
    resolved = manifest.pointers.get(requested_version)
    if resolved:
        return resolved

    # Exact version lookup
    if requested_version in manifest.versions:
        return requested_version

    # Fallback: walk up from exact -> minor -> major pointer.
    # Handles cases like a yanked exact version or removed minor series.
    parts = requested_version.split(".")
    while parts:
        parts.pop()
        fallback = ".".join(parts)
        if fallback:
            resolved = manifest.pointers.get(fallback)
            if resolved:
                return resolved

    return None
