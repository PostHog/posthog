"""
Training result ingestion: finalize a completed TaskRun for an autoresearch pipeline.

The agent records iterations live (autoresearch-training-runs-iterations-create), uploads
its model bundle (autoresearch-training-runs-artifacts-upload-create), and finalizes the
run itself (autoresearch-training-runs-complete-create). This handler is the safety net
for the case where the TaskRun ends without the agent having called complete: if it
recorded iterations, we finalize through the same server-side promotion flow; otherwise
the run produced nothing and is marked failed.

Entry point:
  - handle_task_run_completed(task_run): called from the TaskRun post_save signal
    registered in apps.py. Runs synchronously in the Temporal worker thread.
"""

from __future__ import annotations

from typing import Any

from django.utils import timezone as django_timezone

import structlog

from products.autoresearch.backend.models import AutoresearchIteration, AutoresearchTrainingRun
from products.autoresearch.backend.promotion import complete_training_run

logger = structlog.get_logger(__name__)


def handle_task_run_completed(task_run: Any) -> None:
    """
    Finalize a completed (or failed/cancelled) TaskRun for an autoresearch pipeline.

    Called from the post_save signal in apps.py. Safe to call multiple times — the
    training_run status check prevents double-finalization. Normally the agent finalizes
    the run itself via the complete tool, in which case the run is no longer RUNNING by
    the time this fires and we no-op.
    """
    training_run_id = (task_run.state or {}).get("autoresearch_training_run_id")
    if not training_run_id:
        return

    try:
        training_run = AutoresearchTrainingRun.objects.select_related("pipeline__team").get(id=training_run_id)
    except AutoresearchTrainingRun.DoesNotExist:
        logger.warning(
            "autoresearch_training_run_not_found",
            task_run_id=str(task_run.id),
            training_run_id=training_run_id,
        )
        return

    # Idempotency guard: only act on a still-running run. If the agent already called
    # complete, the run is COMPLETED/FAILED and there is nothing to do.
    if training_run.status != AutoresearchTrainingRun.Status.RUNNING:
        logger.info(
            "autoresearch_training_run_already_processed",
            training_run_id=training_run_id,
            status=training_run.status,
        )
        return

    from products.tasks.backend.models import TaskRun

    if task_run.status in {TaskRun.Status.FAILED, TaskRun.Status.CANCELLED}:
        _mark_failed(training_run, error=task_run.error_message or "TaskRun did not complete successfully")
        return

    # The agent ended without calling complete. If it recorded iterations, finalize through
    # the promotion flow (which also attaches an uploaded bundle as the champion's artifact).
    # If it recorded nothing, the run produced no candidate model — fail it.
    if not AutoresearchIteration.objects.filter(training_run=training_run).exists():
        _mark_failed(training_run, error="Agent recorded no iterations before the run ended.")
        return

    try:
        complete_training_run(training_run)
    except Exception:
        logger.exception(
            "autoresearch_agent_recorded_complete_failed",
            training_run_id=training_run_id,
            task_run_id=str(task_run.id),
        )
        _mark_failed(training_run, error="Agent-recorded run completion failed — see server logs")


def _mark_failed(training_run: AutoresearchTrainingRun, error: str) -> None:
    training_run.status = AutoresearchTrainingRun.Status.FAILED
    training_run.completed_at = django_timezone.now()
    training_run.error = error[:2000]
    training_run.save(update_fields=["status", "completed_at", "error"])
    logger.warning(
        "autoresearch_training_failed",
        training_run_id=str(training_run.pk),
        pipeline_id=str(training_run.pipeline_id),
        error=error,
    )
