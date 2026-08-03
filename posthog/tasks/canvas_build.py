import structlog
from celery import shared_task

from posthog.exceptions_capture import capture_exception
from posthog.tasks.utils import CeleryQueue

logger = structlog.get_logger(__name__)


@shared_task(
    ignore_result=True, queue=CeleryQueue.DEFAULT.value, max_retries=3, autoretry_for=(Exception,), retry_backoff=True
)
def process_canvas_build(team_id: int, build_id: str) -> None:
    """Run one queued canvas build (idempotent — finished builds are a no-op)."""
    from posthog.api.file_system.canvas_build_service import (
        run_canvas_build,  # noqa: PLC0415 — keeps the API layer off the Celery import path
    )

    run_canvas_build(team_id, build_id)


@shared_task(ignore_result=True, queue=CeleryQueue.DEFAULT.value)
def cleanup_canvas_builds() -> None:
    """Apply the canvas artifact retention policy (daily)."""
    from posthog.api.file_system.canvas_build_service import (  # noqa: PLC0415 — keeps the API layer off the Celery import path
        cleanup_canvas_builds as run_cleanup,
    )

    try:
        pruned = run_cleanup()
        if pruned:
            logger.info("canvas_builds_pruned", count=pruned)
    except Exception as error:
        logger.exception("canvas_build_cleanup_failed", error=str(error))
        capture_exception(error, additional_properties={"task": "cleanup_canvas_builds"})
