"""
Django signal receivers for the autoresearch product.

Registered in AutoresearchConfig.ready() (apps.py) after the app registry
is initialised so cross-product model imports are safe.
"""

from typing import Any

import structlog

from posthog.models.scoping import team_scope

logger = structlog.get_logger(__name__)


def on_task_run_saved(sender: Any, instance: Any, created: bool, **kwargs: Any) -> None:
    """
    Detect autoresearch TaskRun completion and trigger recipe ingestion.

    Fires on every TaskRun post_save. Fast-path: reads instance.state (no I/O)
    to bail out quickly for non-autoresearch runs.
    """
    if created:
        return

    # Both imports are deferred: this receiver is connected during django.setup(), and
    # the ingestion path reaches pandas. Importing either at module level puts that cost
    # on every process boot (see posthog/test/repo_invariants/test_startup_import_budget.py).
    from products.tasks.backend.facade.api import TaskRunStatus  # noqa: PLC0415

    if instance.status not in {
        TaskRunStatus.COMPLETED,
        TaskRunStatus.FAILED,
        TaskRunStatus.CANCELLED,
    }:
        return

    training_run_id = (instance.state or {}).get("autoresearch_training_run_id")
    if not training_run_id:
        return

    try:
        from products.autoresearch.backend.training.ingestion import handle_task_run_completed  # noqa: PLC0415

        # The signal is the entry boundary for this path, so it sets the team scope the
        # fail-closed managers need.
        with team_scope(instance.team_id):
            handle_task_run_completed(instance)
    except Exception:
        logger.exception(
            "autoresearch_signal_handler_failed",
            task_run_id=str(instance.id),
            training_run_id=training_run_id,
        )
