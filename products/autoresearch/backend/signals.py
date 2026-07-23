"""
Django signal receivers for the autoresearch product.

Registered in AutoresearchConfig.ready() (apps.py) after the app registry
is initialised so cross-product model imports are safe.
"""

from typing import Any

import structlog

logger = structlog.get_logger(__name__)


def on_task_run_saved(sender: Any, instance: Any, created: bool, **kwargs: Any) -> None:
    """
    Detect autoresearch TaskRun completion and trigger recipe ingestion.

    Fires on every TaskRun post_save. Fast-path: reads instance.state (no I/O)
    to bail out quickly for non-autoresearch runs.
    """
    if created:
        return

    from products.tasks.backend.models import TaskRun

    if instance.status not in {
        TaskRun.Status.COMPLETED,
        TaskRun.Status.FAILED,
        TaskRun.Status.CANCELLED,
    }:
        return

    training_run_id = (instance.state or {}).get("autoresearch_training_run_id")
    if not training_run_id:
        return

    try:
        from products.autoresearch.backend.training_ingestion import handle_task_run_completed

        handle_task_run_completed(instance)
    except Exception:
        logger.exception(
            "autoresearch_signal_handler_failed",
            task_run_id=str(instance.id),
            training_run_id=training_run_id,
        )
