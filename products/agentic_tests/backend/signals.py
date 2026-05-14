"""Django signals for agentic_tests — registered in AppConfig.ready()."""

from django.db.models.signals import post_save
from django.dispatch import receiver

import structlog

logger = structlog.get_logger(__name__)

# Track which task runs have already been processed to avoid duplicate creation
_processed_run_ids: set[str] = set()


def register_task_run_signal() -> None:
    """Register a post_save receiver for TaskRun to handle detect-flows completion."""
    from products.tasks.backend.models import Task, TaskRun

    @receiver(post_save, sender=TaskRun)
    def handle_task_run_save(sender: type, instance: TaskRun, created: bool, **kwargs: object) -> None:
        if created:
            return
        if not instance.output:
            return

        # Only react to saves that actually wrote the output field.
        # set_output uses update_fields=["output", "updated_at"], while
        # mark_completed uses update_fields=["status", "completed_at"].
        # Without this, the signal fires twice across processes and
        # _processed_run_ids (in-memory, per-process) can't deduplicate.
        update_fields = kwargs.get("update_fields")
        if update_fields is not None and "output" not in update_fields:
            return

        run_id = str(instance.id)
        if run_id in _processed_run_ids:
            return

        # Avoid loading the full Task for non-matching runs
        if not Task.objects.filter(id=instance.task_id, origin_product=Task.OriginProduct.AGENTIC_TESTS).exists():
            return

        logger.info(
            "agentic_tests.detect_flows_signal_fired",
            task_run_id=run_id,
            task_id=str(instance.task_id),
            output_keys=list(instance.output.keys())
            if isinstance(instance.output, dict)
            else type(instance.output).__name__,
        )

        try:
            from products.agentic_tests.backend.logic.detect_flows import handle_detect_flows_completion

            handle_detect_flows_completion(instance)
            _processed_run_ids.add(run_id)
        except Exception:
            logger.exception(
                "agentic_tests.detect_flows_completion_failed",
                task_run_id=run_id,
            )
