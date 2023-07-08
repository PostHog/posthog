import datetime as dt
from dataclasses import asdict, dataclass
from uuid import UUID, uuid4

from asgiref.sync import async_to_sync, sync_to_async
from temporalio.api.workflowservice.v1 import ResetWorkflowExecutionRequest
from temporalio.client import (
    Client,
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleBackfill,
    ScheduleIntervalSpec,
    ScheduleOverlapPolicy,
    ScheduleSpec,
    ScheduleState,
)

from posthog import settings
from posthog.batch_exports.models import (
    BatchExport,
    BatchExportDestination,
    BatchExportRun,
)
from posthog.temporal.client import sync_connect


@dataclass
class S3BatchExportInputs:
    """Inputs for S3 export workflow.

    Attributes:
        bucket_name: The S3 bucket we are exporting to.
        region: The AWS region where the bucket is located.
        file_name_prefix: A prefix for the file name to be created in S3.
        batch_window_size: The size in seconds of the batch window.
            For example, for one hour batches, this should be 3600.
        team_id: The team_id whose data we are exporting.
        file_format: The format of the file to be created in S3, supported by ClickHouse.
            A list of all supported formats can be found in https://clickhouse.com/docs/en/interfaces/formats.
        data_interval_end: For manual runs, the end date of the batch. This should be set to `None` for regularly
            scheduled runs and for backfills.
    """

    bucket_name: str
    region: str
    prefix: str
    batch_window_size: int
    team_id: int
    batch_export_id: str
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None
    data_interval_end: str | None = None


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
    table_name: str = "events"
    data_interval_end: str | None = None


DESTINATION_WORKFLOWS = {
    "S3": ("s3-export", S3BatchExportInputs),
    "Snowflake": ("snowflake-export", SnowflakeBatchExportInputs),
}


class BatchExportServiceError(Exception):
    """Base class for BatchExport service exceptions."""


class BatchExportIdError(BatchExportServiceError):
    """Exception raised when an id for a BatchExport is not found."""

    def __init__(self, batch_export_id: str):
        super().__init__(f"No BatchExport found with ID: '{batch_export_id}'")


class BatchExportServiceRPCError(BatchExportServiceError):
    """Exception raised when the underlying Temporal RPC fails."""


@async_to_sync
async def create_schedule(temporal: Client, id: str, schedule: Schedule, trigger_immediately: bool = False):
    """Create a Temporal Schedule."""
    return await temporal.create_schedule(
        id=id,
        schedule=schedule,
        trigger_immediately=trigger_immediately,
    )


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


def backfill_export(temporal: Client, batch_export_id: str, start_at: dt.datetime, end_at: dt.datetime):
    """Creates an export run for the given BatchExport, and specified time range.

    Arguments:
        start_at: From when to backfill.
        end_at: Up to when to backfill.
    """
    try:
        BatchExport.objects.get(id=batch_export_id)
    except BatchExport.DoesNotExist:
        raise BatchExportIdError(batch_export_id)

    schedule_backfill = ScheduleBackfill(start_at=start_at, end_at=end_at, overlap=ScheduleOverlapPolicy.ALLOW_ALL)
    backfill_schedule(temporal=temporal, schedule_id=batch_export_id, schedule_backfill=schedule_backfill)


@async_to_sync
async def backfill_schedule(temporal: Client, schedule_id: str, schedule_backfill: ScheduleBackfill):
    """Async call the Temporal client to execute a backfill on the given schedule."""
    handle = temporal.get_schedule_handle(schedule_id)
    await handle.backfill(schedule_backfill)


def create_batch_export_run(
    batch_export_id: UUID,
    data_interval_start: str,
    data_interval_end: str,
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
        status=BatchExportRun.Status.STARTING,
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


def create_batch_export(
    team_id: int,
    interval: str,
    name: str,
    destination_data: dict,
    start_at: dt.datetime | None = None,
    end_at: dt.datetime | None = None,
    trigger_immediately: bool = False,
):
    """Create a BatchExport and its underlying Temporal Schedule.

    Args:
        team_id: The team this BatchExport belongs to.
        interval: The time interval the Schedule will use.
        name: An informative name for the BatchExport.
        destination_data: Deserialized data for a BatchExportDestination.
        start_at: No runs will be scheduled before the start_at datetime.
        end_at: No runs will be scheduled after the end_at datetime.
        trigger_immediately: Whether a run should be trigger as soon as the Schedule is created
            or when the next Schedule interval begins.
    """
    destination = BatchExportDestination.objects.create(**destination_data)

    batch_export = BatchExport.objects.create(
        team_id=team_id, name=name, interval=interval, destination=destination, start_at=start_at, end_at=end_at
    )

    workflow, workflow_inputs = DESTINATION_WORKFLOWS[batch_export.destination.type]

    state = ScheduleState(
        note=f"Schedule created for BatchExport {batch_export.id} to Destination {batch_export.destination.id} in Team {batch_export.team.id}.",
        paused=batch_export.paused,
    )

    temporal = sync_connect()

    time_delta_from_interval = dt.timedelta(hours=1) if interval == "hour" else dt.timedelta(days=1)

    create_schedule(
        temporal,
        id=str(batch_export.id),
        schedule=Schedule(
            action=ScheduleActionStartWorkflow(
                workflow,
                asdict(
                    workflow_inputs(
                        team_id=batch_export.team.id,
                        # We could take the batch_export_id from the Workflow id
                        # But temporal appends a timestamp at the end we would have to parse out.
                        batch_export_id=str(batch_export.id),
                        **batch_export.destination.config,
                    )
                ),
                id=str(batch_export.id),
                task_queue=settings.TEMPORAL_TASK_QUEUE,
            ),
            spec=ScheduleSpec(
                start_at=start_at,
                end_at=end_at,
                intervals=[ScheduleIntervalSpec(every=time_delta_from_interval)],
            ),
            state=state,
        ),
        trigger_immediately=trigger_immediately,
    )

    return batch_export


async def acreate_batch_export(team_id: int, interval: str, name: str, destination_data: dict) -> BatchExport:
    """Create a BatchExport and its underlying Schedule."""
    return await sync_to_async(create_batch_export)(team_id, interval, name, destination_data)  # type: ignore


def fetch_batch_export_runs(batch_export_id: UUID, limit: int = 100) -> list[BatchExportRun]:
    """Fetch the BatchExportRuns for a given BatchExport."""
    return list(BatchExportRun.objects.filter(batch_export_id=batch_export_id).order_by("-created_at")[:limit])


async def afetch_batch_export_runs(batch_export_id: UUID, limit: int = 100) -> list[BatchExportRun]:
    """Fetch the BatchExportRuns for a given BatchExport."""
    return await sync_to_async(fetch_batch_export_runs)(batch_export_id, limit)  # type: ignore


@async_to_sync
async def reset_batch_export_run(temporal, batch_export_id: str | UUID) -> str:
    """Reset an individual batch export run corresponding to a given batch export.

    Resetting a workflow is considered an "advanced concept" by Temporal, hence it's not exposed
    cleanly via the SDK, and it requries us to make a raw request.

    Resetting a workflow will create a new run with the same workflow id. The new run will have a
    reference to the original run_id that we can use to tie up re-runs with their originals.

    Returns:
        The run_id assigned to the new run.
    """
    request = ResetWorkflowExecutionRequest(
        namespace=settings.TEMPORAL_NAMESPACE,
        workflow_execution={
            "workflow_id": str(batch_export_id),
        },
        # Any unique identifier for the request would work.
        request_id=str(uuid4()),
        # Reset can only happen from 'WorkflowTaskStarted' events. The first one always has id = 3.
        # In other words, this means "reset from the beginning".
        workflow_task_finish_event_id=3,
    )
    resp = await temporal.workflow_service.reset_workflow_execution(request)

    return resp.run_id
