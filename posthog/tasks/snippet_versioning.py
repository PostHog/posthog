import json
import hashlib

from django.conf import settings
from django.core.cache import cache

import structlog
from celery import shared_task

from posthog.models.snippet_versioning import (
    REDIS_POINTER_MAP_KEY,
    S3_VERSIONS_KEY,
    compute_pointer_map,
    validate_version_artifacts,
)
from posthog.storage import object_storage
from posthog.tasks.utils import CeleryQueue

logger = structlog.get_logger(__name__)

# Hash of last synced manifest, used to skip redundant updates
_LAST_HASH_REDIS_KEY = "posthog_js_versions_last_hash"


@shared_task(ignore_result=True, queue=CeleryQueue.DEFAULT.value)
def sync_posthog_js_versions() -> None:
    """Read versions.json from S3, compute pointer map, update Redis if changed."""
    if not settings.POSTHOG_JS_S3_BUCKET:
        return

    try:
        raw = object_storage.read(
            S3_VERSIONS_KEY,
            bucket=settings.POSTHOG_JS_S3_BUCKET,
            missing_ok=True,
        )
    except Exception:
        logger.exception("Failed to read posthog-js/versions.json from S3")
        return

    if raw is None:
        logger.warning("posthog-js/versions.json not found in S3")
        return

    # Skip if manifest hasn't changed
    new_hash = hashlib.sha256(raw.encode()).hexdigest()
    existing_hash = cache.get(_LAST_HASH_REDIS_KEY)
    if existing_hash == new_hash:
        return

    entries = json.loads(raw)
    pointers = compute_pointer_map(entries)

    # Validate that major pin targets have artifacts (these serve the most traffic)
    major_pins = {pin: ver for pin, ver in pointers.items() if "." not in pin}
    for pin, version in major_pins.items():
        if not validate_version_artifacts(version):
            logger.error(
                "Rejecting versions.json update: artifacts missing for major pin",
                pin=pin,
                version=version,
            )
            return

    cache.set(REDIS_POINTER_MAP_KEY, json.dumps(pointers), timeout=None)
    cache.set(_LAST_HASH_REDIS_KEY, new_hash, timeout=None)
    logger.info("Updated posthog-js pointer map", pointers=pointers)
