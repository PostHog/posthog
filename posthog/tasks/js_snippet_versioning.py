from django.conf import settings

import structlog
from celery import shared_task

from posthog.exceptions_capture import capture_exception
from posthog.models.js_snippet_versioning import sync_manifest_from_s3
from posthog.tasks.utils import CeleryQueue

logger = structlog.get_logger(__name__)


@shared_task(ignore_result=True, queue=CeleryQueue.DEFAULT.value)
def sync_js_snippet_manifest() -> None:
    """Read versions.json from S3, compute pointer map, update Redis if changed."""
    if not settings.POSTHOG_JS_S3_BUCKET:
        return

    try:
        manifest = sync_manifest_from_s3()
        logger.info("Updated posthog-js version manifest", manifest=manifest)
    except Exception as e:
        logger.exception("Failed to sync version manifest", error=str(e))
        capture_exception(e, additional_properties={"tag": "js_snippet_versioning", "task": "sync_js_snippet_manifest"})
