"""
Close training runs that their TaskRun can no longer close.

A training run reaches a terminal status only through the agent's complete call or the
``TaskRun`` post_save receiver in ``ingestion.py``. When the sandbox dies hard, or the receiver
never runs, the run stays open, and every training start of its pipeline refuses to run.

Two cases:
  - ``missed_handoff``: the TaskRun is terminal, but the training run is still open. The reaper
    calls the receiver's handler, so the run ends with the outcome it would have had.
  - ``lost_driver``: the TaskRun is still live, or it no longer exists. The reaper fails the run
    and cancels the TaskRun best-effort.

A run with no TaskRun (an external run from ``open_training_run()``, or a stub) is not reaped.
"""

from __future__ import annotations

from datetime import timedelta
from enum import StrEnum
from uuid import UUID

from django.db import transaction
from django.db.models import Q, QuerySet
from django.utils import timezone as django_timezone

import structlog
from prometheus_client import Counter

from posthog.models.scoping import team_scope

from products.autoresearch.backend.models import AutoresearchTrainingRun
from products.autoresearch.backend.training.ingestion import _apply_failure, handle_task_run_completed
from products.tasks.backend.facade import (
    api as tasks_facade,
    cancellation as tasks_cancellation,
)

logger = structlog.get_logger(__name__)

# A sandbox stops at its TTL, so a run older than twice the TTL has no live agent behind it.
# The margin keeps a run that is near its wall clock safe from the reaper.
STALE_TRAINING_RUN_AFTER = timedelta(seconds=2 * tasks_facade.MAX_SANDBOX_TTL_SECONDS)

_OPEN_STATUSES = (AutoresearchTrainingRun.Status.PENDING, AutoresearchTrainingRun.Status.RUNNING)

STALE_TRAINING_RUNS_REAPED = Counter(
    "autoresearch_stale_training_runs_reaped_total",
    "Training runs that the stale-run reaper closed, by case.",
    labelnames=["case"],
)


class ReapCase(StrEnum):
    LOST_DRIVER = "lost_driver"
    MISSED_HANDOFF = "missed_handoff"


def fail_stale_training_runs(*, team_id: int | None = None, pipeline_id: str | UUID | None = None) -> int:
    """
    Close every open training run older than ``STALE_TRAINING_RUN_AFTER`` and return how many it closed.

    With no ``team_id`` it reads every team. Call it outside a transaction, because the finalize
    path reads object storage and takes its own locks.
    """
    reaped = 0
    for run in _stale_runs(team_id=team_id, pipeline_id=pipeline_id):
        try:
            with team_scope(run.team_id):
                case = _reap(run)
        except Exception:
            logger.exception("autoresearch_stale_training_run_reap_failed", training_run_id=str(run.pk))
            continue
        if case is None:
            continue
        reaped += 1
        STALE_TRAINING_RUNS_REAPED.labels(case=case).inc()
        logger.warning(
            "autoresearch_stale_training_run_reaped",
            training_run_id=str(run.pk),
            pipeline_id=str(run.pipeline_id),
            team_id=run.team_id,
            task_run_id=str(run.task_run_id),
            case=case,
        )
    return reaped


def _stale_runs(*, team_id: int | None, pipeline_id: str | UUID | None) -> QuerySet[AutoresearchTrainingRun]:
    cutoff = django_timezone.now() - STALE_TRAINING_RUN_AFTER
    runs = (
        AutoresearchTrainingRun.objects.unscoped()
        if team_id is None
        else AutoresearchTrainingRun.objects.for_team(team_id)
    )
    runs = runs.filter(
        Q(started_at__lt=cutoff) | Q(started_at__isnull=True, created_at__lt=cutoff),
        status__in=_OPEN_STATUSES,
        task_run_id__isnull=False,
    )
    if pipeline_id is not None:
        runs = runs.filter(pipeline__pk=pipeline_id)
    return runs.order_by("created_at")


def _reap(run: AutoresearchTrainingRun) -> ReapCase | None:
    if run.task_run_id is None:
        return None
    task_run = tasks_facade.get_task_run(run.task_run_id, team_id=run.team_id)
    if task_run is not None and task_run.is_terminal:
        handle_task_run_completed(task_run)
        run.refresh_from_db(fields=["status"])
        if run.status not in _OPEN_STATUSES:
            return ReapCase.MISSED_HANDOFF
        # The handler skips a PENDING run and a TaskRun without the state marker.
        failed = _fail_if_open(run, error="The training task ended, but the run was not finalized.")
        return ReapCase.MISSED_HANDOFF if failed else None

    failed = _fail_if_open(
        run,
        error="The training sandbox stopped without a result. The run was open longer than the sandbox can live.",
    )
    if not failed:
        return None
    if task_run is not None:
        _cancel_task_run(task_run.id, task_run.task_id, team_id=run.team_id)
    return ReapCase.LOST_DRIVER


def _fail_if_open(run: AutoresearchTrainingRun, error: str) -> bool:
    with transaction.atomic():
        # Re-read under the lock completion takes, so a run that completed in the meantime keeps its outcome.
        locked = AutoresearchTrainingRun.objects.select_for_update().get(pk=run.pk)
        if locked.status not in _OPEN_STATUSES:
            return False
        _apply_failure(locked, error)
    return True


def _cancel_task_run(task_run_id: UUID, task_id: UUID, *, team_id: int) -> None:
    try:
        outcome, _ = tasks_cancellation.cancel_task_run(
            task_run_id, task_id, team_id, reason="Autoresearch training run was stale", source="autoresearch"
        )
    except Exception:
        logger.exception("autoresearch_stale_training_cancel_failed", task_run_id=str(task_run_id))
        return
    if outcome not in ("accepted", "already_terminal", "not_found"):
        logger.warning("autoresearch_stale_training_cancel_not_accepted", task_run_id=str(task_run_id), outcome=outcome)
