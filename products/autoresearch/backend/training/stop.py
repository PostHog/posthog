"""
Stop a live training run on a person's request.

The run fails under the row lock that completion takes, so a run that completed first keeps its
outcome. The ``TaskRun`` receiver in ``ingestion.py`` acts only on a running run, so it skips the
run when the cancelled ``TaskRun`` ends, and nothing is promoted. The iterations the run recorded stay.
"""

from __future__ import annotations

import structlog

from posthog.models.scoping import team_scope

from products.autoresearch.backend.models import AutoresearchTrainingRun
from products.autoresearch.backend.training.stale import _fail_if_open
from products.tasks.backend.facade import (
    api as tasks_facade,
    cancellation as tasks_cancellation,
)

logger = structlog.get_logger(__name__)

STOPPED_ERROR = "A user stopped this training run before it finished. No model was promoted."


def stop_training_run(run: AutoresearchTrainingRun, *, user_id: int | None) -> bool:
    """
    Fail an open run, then cancel its sandbox best-effort. Returns False when the run was no longer open.

    A run with no ``TaskRun`` (an external run from ``open_training_run()``) only fails.
    """
    with team_scope(run.team_id):
        if not _fail_if_open(run, error=STOPPED_ERROR):
            return False
    logger.info(
        "autoresearch_training_run_stopped",
        training_run_id=str(run.pk),
        pipeline_id=str(run.pipeline_id),
        team_id=run.team_id,
        task_run_id=str(run.task_run_id),
        user_id=user_id,
    )
    if run.task_run_id is not None:
        _cancel_task_run(run, user_id=user_id)
    return True


def _cancel_task_run(run: AutoresearchTrainingRun, *, user_id: int | None) -> None:
    try:
        task_run = tasks_facade.get_task_run(run.task_run_id, team_id=run.team_id)
        if task_run is None:
            return
        outcome, _ = tasks_cancellation.cancel_task_run(
            task_run.id,
            task_run.task_id,
            run.team_id,
            reason="A user stopped the autoresearch training run",
            source="autoresearch",
            requested_by_user_id=user_id,
        )
    except Exception:
        logger.exception("autoresearch_stop_training_cancel_failed", task_run_id=str(run.task_run_id))
        return
    if outcome not in ("accepted", "already_terminal", "not_found"):
        logger.warning(
            "autoresearch_stop_training_cancel_not_accepted", task_run_id=str(run.task_run_id), outcome=outcome
        )
