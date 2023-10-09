import datetime as dt
import typing
from dataclasses import asdict, dataclass, fields
from uuid import UUID

from asgiref.sync import async_to_sync
from temporalio.client import (
    Client,
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleBackfill,
    ScheduleIntervalSpec,
    ScheduleOverlapPolicy,
    SchedulePolicy,
    ScheduleSpec,
    ScheduleState,
    ScheduleUpdate,
    ScheduleUpdateInput,
)

from posthog import settings
from posthog.batch_exports.models import (
    BatchExport,
    BatchExportRun,
)
from posthog.temporal.client import sync_connect


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


DESTINATION_WORKFLOWS = {
    "S3": ("s3-export", S3BatchExportInputs),
    "Snowflake": ("snowflake-export", SnowflakeBatchExportInputs),
    "Postgres": ("postgres-export", PostgresBatchExportInputs),
    "BigQuery": ("bigquery-export", BigQueryBatchExportInputs),
}


class BatchExportServiceError(Exception):
    """Base class for BatchExport service exceptions."""


class BatchExportIdError(BatchExportServiceError):
    """Exception raised when an id for a BatchExport is not found."""

    def __init__(self, batch_export_id: str):
        super().__init__(f"No BatchExport found with ID: '{batch_export_id}'")


class BatchExportServiceRPCError(BatchExportServiceError):
    """Exception raised when the underlying Temporal RPC fails."""


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


@async_to_sync
async def pause_schedule(temporal: Client, schedule_id: str, note: str | None = None) -> None:
    """Pause a Temporal Schedule."""
    handle = temporal.get_schedule_handle(schedule_id)
    await handle.pause(note=note)


def unpause_batch_export(
    temporal: Client, batch_export_id: str, note: str | None = None, backfill: bool = False
) -> None:
    """Pause this BatchExport.

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


@async_to_sync
async def unpause_schedule(temporal: Client, schedule_id: str, note: str | None = None) -> None:
    """Unpause a Temporal Schedule."""
    handle = temporal.get_schedule_handle(schedule_id)
    await handle.unpause(note=note)


@async_to_sync
async def delete_schedule(temporal: Client, schedule_id: str) -> None:
    """Delete a Temporal Schedule."""
    handle = temporal.get_schedule_handle(schedule_id)
    await handle.delete()


@async_to_sync
async def describe_schedule(temporal: Client, schedule_id: str):
    """Describe a Temporal Schedule."""
    handle = temporal.get_schedule_handle(schedule_id)
    return await handle.describe()


def backfill_export(
    temporal: Client,
    batch_export_id: str,
    start_at: dt.datetime,
    end_at: dt.datetime,
    overlap: ScheduleOverlapPolicy = ScheduleOverlapPolicy.BUFFER_ALL,
):
    """Creates an export run for the given BatchExport, and specified time range.

    Arguments:
        start_at: From when to backfill.
        end_at: Up to when to backfill.
    """
    try:
        BatchExport.objects.get(id=batch_export_id)
    except BatchExport.DoesNotExist:
        raise BatchExportIdError(batch_export_id)

    schedule_backfill = ScheduleBackfill(start_at=start_at, end_at=end_at, overlap=overlap)
    backfill_schedule(temporal=temporal, schedule_id=batch_export_id, schedule_backfill=schedule_backfill)


@async_to_sync
async def backfill_schedule(temporal: Client, schedule_id: str, schedule_backfill: ScheduleBackfill):
    """Async call the Temporal client to execute a backfill on the given schedule."""
    handle = temporal.get_schedule_handle(schedule_id)
    description = await handle.describe()

    if description.schedule.spec.jitter is not None:
        schedule_backfill.end_at += description.schedule.spec.jitter

    await handle.backfill(schedule_backfill)


def create_batch_export_run(
    batch_export_id: UUID,
    data_interval_start: str,
    data_interval_end: str,
    status: str = BatchExportRun.Status.STARTING,
):
    """Create a BatchExportRun after a Temporal Workflow execution.

    In a first approach, this method is intended to be called only by Temporal Workflows,
    as only the Workflows themselves can know when they start.

    Args:
        data_interval_start:
        data_interval_end:
    """
    run = BatchExportRun(
        batch_export_id=batch_export_id,
        status=status,
        data_interval_start=dt.datetime.fromisoformat(data_interval_start),
        data_interval_end=dt.datetime.fromisoformat(data_interval_end),
    )
    run.save()

    return run


def update_batch_export_run_status(run_id: UUID, status: str, latest_error: str | None):
    """Update the status of an BatchExportRun with given id.

    Arguments:
        id: The id of the BatchExportRun to update.
    """
    updated = BatchExportRun.objects.filter(id=run_id).update(status=status, latest_error=latest_error)
    if not updated:
        raise ValueError(f"BatchExportRun with id {run_id} not found.")


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
            task_queue=settings.TEMPORAL_TASK_QUEUE,
        ),
        spec=ScheduleSpec(
            start_at=batch_export.start_at,
            end_at=batch_export.end_at,
            intervals=[ScheduleIntervalSpec(every=batch_export.interval_time_delta)],
        ),
        state=state,
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.ALLOW_ALL),
    )

    if created:
        create_schedule(temporal, id=str(batch_export.id), schedule=schedule)
    else:
        update_schedule(temporal, id=str(batch_export.id), schedule=schedule)

    return batch_export


@async_to_sync
async def create_schedule(temporal: Client, id: str, schedule: Schedule, trigger_immediately: bool = False):
    """Create a Temporal Schedule."""
    return await temporal.create_schedule(
        id=id,
        schedule=schedule,
        trigger_immediately=trigger_immediately,
    )


@async_to_sync
async def update_schedule(temporal: Client, id: str, schedule: Schedule) -> None:
    """Update a Temporal Schedule."""
    handle = temporal.get_schedule_handle(id)

    async def updater(_: ScheduleUpdateInput) -> ScheduleUpdate:
        return ScheduleUpdate(schedule=schedule)

    return await handle.update(
        updater=updater,
    )
