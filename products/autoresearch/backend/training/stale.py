"""
Reap stranded autoresearch training runs whose sandbox or worker died.

Autoresearch backlog id: A1.

A training run whose sandbox dies blocks its pipeline's training for good, because
``activity_kickoff_training()`` and ``start_training()`` refuse to launch while a run is
PENDING or RUNNING. This module detects stale runs past a generous multiple of
``MAX_SANDBOX_TTL_SECONDS`` and closes them:
- Terminal TaskRun: finalizes through ``handle_task_run_completed()`` (missed hand-off).
- Live/missing TaskRun or no task: marks the run FAILED and cancels the TaskRun best-effort (lost driver).
External runs opened via ``open_training_run()`` are left alone.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING
from uuid import UUID

from django.db import transaction
from django.utils import timezone as django_timezone

from prometheus_client import Counter
import structlog

from products.autoresearch.backend.models import AutoresearchPipeline, AutoresearchTrainingRun
from products.autoresearch.backend.training.ingestion import handle_task_run_completed
from products.tasks.backend.facade import api as tasks_facade, cancellation as tasks_cancellation
from products.tasks.backend.facade.sandbox import MAX_SANDBOX_TTL_SECONDS

if TYPE_CHECKING:
    from products.tasks.backend.facade.contracts import TaskRunDTO

logger = structlog.get_logger(__name__)

AUTORESEARCH_STALE_TRAINING_RUNS_REAPED = Counter(
    "autoresearch_stale_training_runs_reaped_total",
    "Stranded training runs reaped by the stale-runs backstop.",
    labelnames=["case"],
)

# Generous multiple of sandbox TTL: ensures a run running near its wall clock
# is never reaped out from under itself.
DEFAULT_STALE_TRAINING_RUN_CUTOFF = timedelta(seconds=2 * MAX_SANDBOX_TTL_SECONDS)


class _FinishedTaskRunAdapter:
    """Wraps a TaskRunDTO so it satisfies FinishedTaskRun and ensures the training run id marker is present."""

    def __init__(self, dto: TaskRunDTO, training_run_id: UUID) -> None:
        self._dto = dto
        self._training_run_id = training_run_id

    @property
    def id(self) -> UUID:
        return self._dto.id

    @property
    def team_id(self) -> int:
        return self._dto.team_id

    @property
    def status(self) -> str:
        return self._dto.status

    @property
    def state(self) -> dict:
        state = dict(self._dto.state or {})
        state.setdefault("autoresearch_training_run_id", str(self._training_run_id))
        return state

    @property
    def error_message(self) -> str | None:
        return self._dto.error_message


def _cancel_dispatched_task_run(task_run_id: UUID, task_id: UUID, *, team_id: int) -> None:
    """Best-effort cancellation of a live or stranded TaskRun. Never raises."""
    try:
        tasks_cancellation.cancel_task_run(
            task_run_id,
            task_id,
            team_id,
            reason="Autoresearch training run timed out past the sandbox TTL ceiling",
            source="autoresearch",
        )
    except Exception:
        logger.exception("autoresearch_stale_training_cancel_failed", task_run_id=str(task_run_id))


def _fail_training_run(training_run_pk: UUID, error: str) -> bool:
    """Mark a training run FAILED under a row lock. Returns True if the status transition succeeded."""
    now = django_timezone.now()
    with transaction.atomic():
        locked = AutoresearchTrainingRun.objects.select_for_update().get(pk=training_run_pk)
        if locked.status not in (
            AutoresearchTrainingRun.Status.PENDING,
            AutoresearchTrainingRun.Status.RUNNING,
        ):
            # Completed or failed concurrently
            return False

        locked.status = AutoresearchTrainingRun.Status.FAILED
        locked.completed_at = now
        locked.error = error[:2000]
        locked.save(update_fields=["status", "completed_at", "error"])

        # If inaugural run, drop pipeline back to DRAFT so it doesn't stay in BOOTSTRAPPING
        AutoresearchPipeline.objects.filter(
            pk=locked.pipeline_id,
            team_id=locked.team_id,
            status=AutoresearchPipeline.Status.BOOTSTRAPPING,
        ).update(status=AutoresearchPipeline.Status.DRAFT, updated_at=now)

    return True


def fail_stale_training_runs(
    team_id: int | None = None,
    pipeline_id: str | UUID | None = None,
    cutoff_delta: timedelta | None = None,
) -> int:
    """
    Reap training runs that are still PENDING or RUNNING past the stale cutoff.

    Cases handled:
    - Missed hand-off: the TaskRun reached a terminal status, but the ingestion signal
      failed or never fired. Finalizes through ``handle_task_run_completed()``.
    - Lost driver: the sandbox/worker died hard or timed out, or no task exists.
      Cancels the TaskRun best-effort and marks the run FAILED.

    External runs opened with ``open_training_run()`` are skipped (they run on the caller's agent).
    Uses conditional updates so a run completing concurrently is not overwritten.
    """
    now = django_timezone.now()
    cutoff_time = now - (cutoff_delta or DEFAULT_STALE_TRAINING_RUN_CUTOFF)

    # Base query for stale runs across teams or scoped to a specific team / pipeline
    if team_id is not None:
        qs = AutoresearchTrainingRun.objects.for_team(team_id)
    else:
        qs = AutoresearchTrainingRun.objects.unscoped()

    qs = qs.filter(
        status__in=[AutoresearchTrainingRun.Status.PENDING, AutoresearchTrainingRun.Status.RUNNING],
        created_at__lt=cutoff_time,
    )

    if pipeline_id is not None:
        qs = qs.filter(pipeline_id=pipeline_id)

    # Exclude external runs: opened with open_training_run(), which have no task_id and no agent_runtime_adapter
    qs = qs.exclude(task_id__isnull=True, agent_runtime_adapter__isnull=True)
    qs = qs.exclude(task_id__isnull=True, agent_runtime_adapter="")

    reaped = 0

    for run in qs:
        case: str | None = None

        if run.task_run_id is not None:
            task_run_dto = tasks_facade.get_task_run(run.task_run_id, team_id=run.team_id)
            if task_run_dto is not None and task_run_dto.is_terminal:
                # Missed hand-off: terminal TaskRun, finalize through the same receiver path
                case = "missed_handoff"
                try:
                    handle_task_run_completed(_FinishedTaskRunAdapter(task_run_dto, run.id))
                except Exception:
                    logger.exception(
                        "autoresearch_stale_training_ingestion_failed",
                        training_run_id=str(run.id),
                        task_run_id=str(run.task_run_id),
                    )
                    _fail_training_run(
                        run.pk,
                        "Finalizing terminal task run failed during stale run reap",
                    )
            else:
                # Lost driver: TaskRun is still live or missing
                case = "lost_driver"
                if run.task_id is not None:
                    _cancel_dispatched_task_run(run.task_run_id, run.task_id, team_id=run.team_id)
                if not _fail_training_run(
                    run.pk,
                    "Training sandbox stopped without a result. The worker was lost or timed out.",
                ):
                    continue
        else:
            # Run has no task_run_id (e.g. lost before task dispatch completed)
            case = "lost_driver"
            if not _fail_training_run(
                run.pk,
                "Training sandbox stopped before task dispatch completed.",
            ):
                continue

        if case:
            AUTORESEARCH_STALE_TRAINING_RUNS_REAPED.labels(case=case).inc()
            logger.warning(
                "autoresearch_stale_training_run_reaped",
                training_run_id=str(run.id),
                pipeline_id=str(run.pipeline_id),
                case=case,
            )
            reaped += 1

    return reaped
