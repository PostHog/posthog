import datetime as dt
import typing
from dataclasses import asdict, dataclass, fields
from uuid import UUID

import temporalio
from asgiref.sync import async_to_sync
from temporalio.client import (
    Client,
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleIntervalSpec,
    ScheduleOverlapPolicy,
    SchedulePolicy,
    ScheduleSpec,
    ScheduleState,
)

from posthog.batch_exports.models import (
    BatchExport,
    BatchExportBackfill,
    BatchExportRun,
)
from posthog.temporal.common.client import sync_connect
from posthog.temporal.common.schedule import (
    create_schedule,
    update_schedule,
    unpause_schedule,
    pause_schedule,
    delete_schedule,
)
from posthog.constants import BATCH_EXPORTS_TASK_QUEUE


class BatchExportsInputsProtocol(typing.Protocol):
    team_id: int


@dataclass
class S3BatchExportInputs:
    """Inputs for S3 export workflow.

    Attributes:
        batch_export_id: The ID of the parent BatchExport.
        team_id: The ID of the team that contains the BatchExport whose data we are exporting.
        interval: The range of data we are exporting.
        bucket_name: The S3 bucket we are exporting to.
        region: The AWS region where the bucket is located.
        prefix: A prefix for the file name to be created in S3.
            For example, for one hour batches, this should be 3600.
        data_interval_end: For manual runs, the end date of the batch. This should be set to `None` for regularly
            scheduled runs and for backfills.
    """

    batch_export_id: str
    team_id: int
    bucket_name: str
    region: str
    prefix: str
    interval: str = "hour"
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None
    data_interval_end: str | None = None
    compression: str | None = None
    exclude_events: list[str] | None = None
    include_events: list[str] | None = None
    encryption: str | None = None
    kms_key_id: str | None = None


@dataclass
class SnowflakeBatchExportInputs:
    """Inputs for Snowflake export workflow."""

    batch_export_id: str
    team_id: int
    user: str
    password: str
    account: str
    database: str
    warehouse: str
    schema: str
    interval: str = "hour"
    table_name: str = "events"
    data_interval_end: str | None = None
    role: str | None = None
    exclude_events: list[str] | None = None
    include_events: list[str] | None = None


@dataclass
class PostgresBatchExportInputs:
    """Inputs for Postgres export workflow."""

    batch_export_id: str
    team_id: int
    user: str
    password: str
    host: str
    database: str
    has_self_signed_cert: bool = False
    interval: str = "hour"
    schema: str = "public"
    table_name: str = "events"
    port: int = 5432
    data_interval_end: str | None = None
    exclude_events: list[str] | None = None
    include_events: list[str] | None = None


@dataclass
class RedshiftBatchExportInputs(PostgresBatchExportInputs):
    """Inputs for Redshift export workflow."""

    properties_data_type: str = "varchar"


@dataclass
class BigQueryBatchExportInputs:
    """Inputs for BigQuery export workflow."""

    batch_export_id: str
    team_id: int
    project_id: str
    dataset_id: str
    private_key: str
    private_key_id: str
    token_uri: str
    client_email: str
    interval: str = "hour"
    table_id: str = "events"
    data_interval_end: str | None = None
    exclude_events: list[str] | None = None
    include_events: list[str] | None = None


@dataclass
class NoOpInputs:
    """NoOp Workflow is used for testing, it takes a single argument to echo back."""

    batch_export_id: str
    team_id: int
    interval: str = "hour"
    arg: str = ""


DESTINATION_WORKFLOWS = {
    "S3": ("s3-export", S3BatchExportInputs),
    "Snowflake": ("snowflake-export", SnowflakeBatchExportInputs),
    "Postgres": ("postgres-export", PostgresBatchExportInputs),
    "Redshift": ("redshift-export", RedshiftBatchExportInputs),
    "BigQuery": ("bigquery-export", BigQueryBatchExportInputs),
    "NoOp": ("no-op", NoOpInputs),
}


class BatchExportServiceError(Exception):
    """Base class for BatchExport service exceptions."""


class BatchExportIdError(BatchExportServiceError):
    """Exception raised when an id for a BatchExport is not found."""

    def __init__(self, batch_export_id: str):
        super().__init__(f"No BatchExport found with ID: '{batch_export_id}'")


class BatchExportServiceRPCError(BatchExportServiceError):
    """Exception raised when the underlying Temporal RPC fails."""


class BatchExportServiceScheduleNotFound(BatchExportServiceRPCError):
    """Exception raised when the underlying Temporal RPC fails because a schedule was not found."""

    def __init__(self, schedule_id: str):
        self.schedule_id = schedule_id
        super().__init__(f"The Temporal Schedule {schedule_id} was not found (maybe it was deleted?)")


def pause_batch_export(temporal: Client, batch_export_id: str, note: str | None = None) -> None:
    """Pause this BatchExport.

    We pass the call to the underlying Temporal Schedule.
    """
    try:
        batch_export = BatchExport.objects.get(id=batch_export_id)
    except BatchExport.DoesNotExist:
        raise BatchExportIdError(batch_export_id)

    if batch_export.paused is True:
        return

    try:
        pause_schedule(temporal, schedule_id=batch_export_id, note=note)
    except Exception as exc:
        raise BatchExportServiceRPCError(f"BatchExport {batch_export_id} could not be paused") from exc

    batch_export.paused = True
    batch_export.last_paused_at = dt.datetime.utcnow()
    batch_export.save()


def unpause_batch_export(
    temporal: Client,
    batch_export_id: str,
    note: str | None = None,
    backfill: bool = False,
) -> None:
    """Unpause this BatchExport.

    We pass the call to the underlying Temporal Schedule. Additionally, we can trigger a backfill
    to backfill runs missed while paused.

    Args:
        temporal: The Temporal client to execute calls.
        batch_export_id: The ID of the BatchExport to unpause.
        note: An optional note to include in the Schedule when unpausing.
        backfill: If True, a backfill will be triggered since the BatchExport's last_paused_at.

    Raises:
        BatchExportIdError: If the provided batch_export_id doesn't point to an existing BatchExport.
    """
    try:
        batch_export = BatchExport.objects.get(id=batch_export_id)
    except BatchExport.DoesNotExist:
        raise BatchExportIdError(batch_export_id)

    if batch_export.paused is False:
        return

    try:
        unpause_schedule(temporal, schedule_id=batch_export_id, note=note)
    except Exception as exc:
        raise BatchExportServiceRPCError(f"BatchExport {batch_export_id} could not be unpaused") from exc

    batch_export.paused = False
    batch_export.save()

    if backfill is False:
        return

    batch_export.refresh_from_db()
    start_at = batch_export.last_paused_at
    end_at = batch_export.last_updated_at

    backfill_export(temporal, batch_export_id, start_at, end_at)


def batch_export_delete_schedule(temporal: Client, schedule_id: str) -> None:
    """Delete a Temporal Schedule."""
    try:
        delete_schedule(temporal, schedule_id)
    except temporalio.service.RPCError as e:
        if e.status == temporalio.service.RPCStatusCode.NOT_FOUND:
            raise BatchExportServiceScheduleNotFound(schedule_id)
        else:
            raise BatchExportServiceRPCError() from e


@async_to_sync
async def cancel_running_batch_export_backfill(temporal: Client, workflow_id: str) -> None:
    """Delete a running BatchExportBackfill.

    A BatchExportBackfill represents a Temporal Workflow. When deleting the Temporal
    Schedule that we are backfilling, we should also clean-up any Workflows that are
    still running.
    """
    handle = temporal.get_workflow_handle(workflow_id=workflow_id)
    await handle.cancel()


@dataclass
class BackfillBatchExportInputs:
    """Inputs for the BackfillBatchExport Workflow."""

    team_id: int
    batch_export_id: str
    start_at: str
    end_at: str
    buffer_limit: int = 1
    wait_delay: float = 5.0


def backfill_export(
    temporal: Client,
    batch_export_id: str,
    team_id: int,
    start_at: dt.datetime,
    end_at: dt.datetime,
) -> str:
    """Starts a backfill for given team and batch export covering given date range.

    Arguments:
        temporal: A Temporal Client to trigger the workflow.
        batch_export_id: The id of the BatchExport to backfill.
        team_id: The id of the Team the BatchExport belongs to.
        start_at: From when to backfill.
        end_at: Up to when to backfill.
    """
    try:
        BatchExport.objects.get(id=batch_export_id, team_id=team_id)
    except BatchExport.DoesNotExist:
        raise BatchExportIdError(batch_export_id)

    inputs = BackfillBatchExportInputs(
        batch_export_id=batch_export_id,
        team_id=team_id,
        start_at=start_at.isoformat(),
        end_at=end_at.isoformat(),
    )
    workflow_id = start_backfill_batch_export_workflow(temporal, inputs=inputs)
    return workflow_id


@async_to_sync
async def start_backfill_batch_export_workflow(temporal: Client, inputs: BackfillBatchExportInputs) -> str:
    """Async call to start a BackfillBatchExportWorkflow."""
    handle = temporal.get_schedule_handle(inputs.batch_export_id)
    description = await handle.describe()

    if description.schedule.spec.jitter is not None:
        # Adjust end_at to account for jitter if present.
        inputs.end_at = (dt.datetime.fromisoformat(inputs.end_at) + description.schedule.spec.jitter).isoformat()

    workflow_id = f"{inputs.batch_export_id}-Backfill-{inputs.start_at}-{inputs.end_at}"
    await temporal.start_workflow(
        "backfill-batch-export",
        inputs,
        id=workflow_id,
        task_queue=BATCH_EXPORTS_TASK_QUEUE,
    )

    return workflow_id


def create_batch_export_run(
    batch_export_id: UUID,
    data_interval_start: str,
    data_interval_end: str,
    status: str = BatchExportRun.Status.STARTING,
) -> BatchExportRun:
    """Create a BatchExportRun after a Temporal Workflow execution.

    In a first approach, this method is intended to be called only by Temporal Workflows,
    as only the Workflows themselves can know when they start.

    Args:
        batch_export_id: The UUID of the BatchExport the BatchExportRun to create belongs to.
        data_interval_start: The start of the period of data exported in this BatchExportRun.
        data_interval_end: The end of the period of data exported in this BatchExportRun.
        status: The initial status for the created BatchExportRun.
    """
    run = BatchExportRun(
        batch_export_id=batch_export_id,
        status=status,
        data_interval_start=dt.datetime.fromisoformat(data_interval_start),
        data_interval_end=dt.datetime.fromisoformat(data_interval_end),
    )
    run.save()

    return run


def update_batch_export_run_status(run_id: UUID, status: str, latest_error: str | None) -> BatchExportRun:
    """Update the status of an BatchExportRun with given id.

    Arguments:
        id: The id of the BatchExportRun to update.
    """
    model = BatchExportRun.objects.filter(id=run_id)
    updated = model.update(status=status, latest_error=latest_error)

    if not updated:
        raise ValueError(f"BatchExportRun with id {run_id} not found.")

    return model.get()


def sync_batch_export(batch_export: BatchExport, created: bool):
    workflow, workflow_inputs = DESTINATION_WORKFLOWS[batch_export.destination.type]
    state = ScheduleState(
        note=f"Schedule updated for BatchExport {batch_export.id} to Destination {batch_export.destination.id} in Team {batch_export.team.id}.",
        paused=batch_export.paused,
    )

    destination_config_fields = set(field.name for field in fields(workflow_inputs))
    destination_config = {k: v for k, v in batch_export.destination.config.items() if k in destination_config_fields}

    temporal = sync_connect()
    schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            workflow,
            asdict(
                workflow_inputs(
                    team_id=batch_export.team.id,
                    batch_export_id=str(batch_export.id),
                    interval=str(batch_export.interval),
                    **destination_config,
                )
            ),
            id=str(batch_export.id),
            task_queue=BATCH_EXPORTS_TASK_QUEUE,
        ),
        spec=ScheduleSpec(
            start_at=batch_export.start_at,
            end_at=batch_export.end_at,
            intervals=[ScheduleIntervalSpec(every=batch_export.interval_time_delta)],
            jitter=(batch_export.interval_time_delta / 12),
        ),
        state=state,
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.ALLOW_ALL),
    )

    if created:
        create_schedule(temporal, id=str(batch_export.id), schedule=schedule)
    else:
        update_schedule(temporal, id=str(batch_export.id), schedule=schedule)

    return batch_export


def create_batch_export_backfill(
    batch_export_id: UUID,
    team_id: int,
    start_at: str,
    end_at: str,
    status: str = BatchExportRun.Status.RUNNING,
) -> BatchExportBackfill:
    """Create a BatchExportBackfill.


    Args:
        batch_export_id: The UUID of the BatchExport the BatchExportBackfill to create belongs to.
        team_id: The id of the Team the BatchExportBackfill to create belongs to.
        start_at: The start of the period to backfill in this BatchExportBackfill.
        end_at: The end of the period to backfill in this BatchExportBackfill.
        status: The initial status for the created BatchExportBackfill.
    """
    backfill = BatchExportBackfill(
        batch_export_id=batch_export_id,
        status=status,
        start_at=dt.datetime.fromisoformat(start_at),
        end_at=dt.datetime.fromisoformat(end_at),
        team_id=team_id,
    )
    backfill.save()

    return backfill


def update_batch_export_backfill_status(backfill_id: UUID, status: str) -> BatchExportBackfill:
    """Update the status of an BatchExportBackfill with given id.

    Arguments:
        id: The id of the BatchExportBackfill to update.
        status: The new status to assign to the BatchExportBackfill.
    """
    model = BatchExportBackfill.objects.filter(id=backfill_id)
    updated = model.update(status=status)

    if not updated:
        raise ValueError(f"BatchExportBackfill with id {backfill_id} not found.")

    return model.get()
