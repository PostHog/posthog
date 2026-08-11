import structlog
from celery import shared_task

from posthog.exceptions_capture import capture_exception
from posthog.tasks.utils import CeleryQueue

logger = structlog.get_logger(__name__)


@shared_task(
    ignore_result=True,
    queue=CeleryQueue.LONG_RUNNING.value,
    max_retries=3,
    autoretry_for=(Exception,),
    retry_backoff=True,
    soft_time_limit=300,
    time_limit=330,
)
def process_canvas_build(team_id: int, build_id: str) -> None:
    """Run one queued canvas build (idempotent — finished builds are a no-op)."""
    # Deferred import keeps the service off the Celery import path.
    from products.canvas.backend.build_service import run_canvas_build  # noqa: PLC0415

    run_canvas_build(team_id, build_id)


@shared_task(ignore_result=True, queue=CeleryQueue.DEFAULT.value)
def sweep_canvas_builds() -> None:
    """Recover builds stuck in flight (every 2 minutes)."""
    from products.canvas.backend.build_service import sweep_canvas_builds as run_sweep  # noqa: PLC0415

    try:
        counts = run_sweep()
        if any(counts.values()):
            logger.info("canvas_builds_swept", **counts)
    except Exception as error:
        logger.exception("canvas_build_sweep_failed", error=str(error))
        capture_exception(error, additional_properties={"task": "sweep_canvas_builds"})


@shared_task(ignore_result=True, queue=CeleryQueue.DEFAULT.value)
def cleanup_canvas_builds() -> None:
    """Apply the canvas artifact retention policy (daily)."""
    from products.canvas.backend.build_service import cleanup_canvas_builds as run_cleanup  # noqa: PLC0415

    try:
        pruned = run_cleanup()
        if pruned:
            logger.info("canvas_builds_pruned", count=pruned)
    except Exception as error:
        logger.exception("canvas_build_cleanup_failed", error=str(error))
        capture_exception(error, additional_properties={"task": "cleanup_canvas_builds"})
