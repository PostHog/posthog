"""Django signals for agentic_tests — registered in AppConfig.ready()."""

from django.db.models.signals import post_save
from django.dispatch import receiver

import structlog

logger = structlog.get_logger(__name__)


def register_task_run_signal() -> None:
    """Register a post_save receiver for TaskRun to handle detect-flows completion."""
    from products.tasks.backend.models import Task, TaskRun

    @receiver(post_save, sender=TaskRun)
    def handle_task_run_save(sender: type, instance: TaskRun, created: bool, **kwargs: object) -> None:
        if created:
            return
        if instance.status != TaskRun.Status.COMPLETED:
            return
        if not instance.output:
            return

        # Avoid loading the full Task for non-matching runs — check via lightweight exists() first
        if not Task.objects.filter(id=instance.task_id, origin_product=Task.OriginProduct.AGENTIC_TESTS).exists():
            return

        try:
            from products.agentic_tests.backend.logic.detect_flows import handle_detect_flows_completion

            handle_detect_flows_completion(instance)
        except Exception:
            logger.exception(
                "agentic_tests.detect_flows_completion_failed",
                task_run_id=str(instance.id),
            )
