from datetime import UTC, datetime
from typing import Any

from django.utils import timezone

import dagster

from posthog.models.async_deletion import DeletionRunJob, DeletionRunLog, DeletionRunStatus

# Run states after which a row still marked running will never be updated by the run itself.
_FINAL_STATUSES = {
    dagster.DagsterRunStatus.SUCCESS: DeletionRunStatus.SUCCEEDED,
    dagster.DagsterRunStatus.FAILURE: DeletionRunStatus.FAILED,
    dagster.DagsterRunStatus.CANCELED: DeletionRunStatus.CANCELED,
}


def _record(instance: dagster.DagsterInstance, run_id: str, job: DeletionRunJob, **fields: Any) -> None:
    # Any step can make the first write, so the start time comes from Dagster and not from the write.
    record = instance.get_run_record_by_id(run_id)
    started_at = datetime.fromtimestamp(record.start_time, UTC) if record and record.start_time else None
    parent_run_id = record.dagster_run.parent_run_id if record else None
    DeletionRunLog.record(run_id, job, parent_run_id, started_at=started_at, **fields)


def record_run(context: dagster.OpExecutionContext, job: DeletionRunJob, **fields: Any) -> None:
    _record(context.instance, context.run_id, job, **fields)


def record_run_succeeded(context: dagster.OpExecutionContext, job: DeletionRunJob) -> None:
    record_run(context, job, status=DeletionRunStatus.SUCCEEDED, finished_at=timezone.now())


def record_run_failed(context: dagster.HookContext, job: DeletionRunJob) -> None:
    _record(
        context.instance,
        context.run_id,
        job,
        status=DeletionRunStatus.FAILED,
        finished_at=timezone.now(),
        error=f"{context.op.name}: {context.op_exception}",
    )


def reconcile_running_logs(instance: dagster.DagsterInstance) -> int:
    """Close rows whose run ended without a step reporting it: a cancel, a crashed worker, a partial op selection."""
    closed = 0
    for log in DeletionRunLog.objects.filter(status=DeletionRunStatus.RUNNING):
        run = instance.get_run_by_id(log.dagster_run_id)
        if run is None:
            status, error = DeletionRunStatus.FAILED, "Dagster has no record of this run."
        elif run.status in _FINAL_STATUSES:
            status = _FINAL_STATUSES[run.status]
            error = (
                "" if status == DeletionRunStatus.SUCCEEDED else f"The run ended as {run.status.value} outside a step."
            )
        else:
            continue
        DeletionRunLog.objects.filter(pk=log.pk, status=DeletionRunStatus.RUNNING).update(
            status=status, finished_at=timezone.now(), error=log.error or error
        )
        closed += 1
    return closed


@dagster.sensor(default_status=dagster.DefaultSensorStatus.RUNNING, minimum_interval_seconds=3600)
def reconcile_deletion_run_logs(context: dagster.SensorEvaluationContext) -> dagster.SkipReason:
    closed = reconcile_running_logs(context.instance)
    return dagster.SkipReason(f"Closed {closed} deletion run log rows whose run had ended.")
