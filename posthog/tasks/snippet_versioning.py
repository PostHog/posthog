import json
import hashlib

from django.conf import settings
from django.core.cache import cache

import structlog
from celery import shared_task

from posthog.models.snippet_versioning import REDIS_LATEST_KEY, validate_version_artifacts
from posthog.storage import object_storage
from posthog.tasks.utils import CeleryQueue

logger = structlog.get_logger(__name__)


@shared_task(ignore_result=True, queue=CeleryQueue.DEFAULT.value)
def sync_posthog_js_latest() -> None:
    """Read latest.json from S3, validate artifacts, update Redis if changed."""
    if not settings.POSTHOG_JS_S3_BUCKET:
        return

    try:
        raw = object_storage.read(
            "posthog-js/latest.json",
            bucket=settings.POSTHOG_JS_S3_BUCKET,
            missing_ok=True,
        )
    except Exception:
        logger.exception("Failed to read posthog-js/latest.json from S3")
        return

    if raw is None:
        logger.warning("posthog-js/latest.json not found in S3")
        return

    # Check if changed
    new_hash = hashlib.sha256(raw.encode()).hexdigest()
    existing = cache.get(REDIS_LATEST_KEY)
    if existing is not None:
        existing_hash = hashlib.sha256(
            existing.encode() if isinstance(existing, str) else json.dumps(existing).encode()
        ).hexdigest()
        if new_hash == existing_hash:
            return

    # Validate artifacts before updating
    pointers = json.loads(raw)
    latest_version = pointers.get("latest")
    if latest_version and not validate_version_artifacts(latest_version):
        logger.error(
            "Rejecting latest.json update: artifacts missing for version",
            version=latest_version,
        )
        return

    cache.set(REDIS_LATEST_KEY, raw, timeout=None)  # No expiry — Celery keeps it fresh
    logger.info("Updated posthog-js latest pointers", pointers=pointers)
