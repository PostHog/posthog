import datetime as dt
from asgiref.sync import sync_to_async
from uuid import UUID

from dataclasses import dataclass, asdict

from rest_framework.exceptions import ValidationError

from posthog import settings
from posthog.batch_exports.models import BatchExport, BatchExportDestination, BatchExportRun
from posthog.temporal.client import sync_connect
from asgiref.sync import async_to_sync


from temporalio.client import (
    Client,
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleIntervalSpec,
    ScheduleSpec,
    ScheduleState,
)


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


@async_to_sync
async def create_schedule(temporal, id: str, schedule: Schedule, trigger_immediately: bool = False):
    """Create a Temporal Schedule."""
    return await temporal.create_schedule(
        id=id,
        schedule=schedule,
        trigger_immediately=trigger_immediately,
    )


def pause_batch_export(temporal: Client, batch_export_id: str, note: str | None = None) -> None:
    """Pause this BatchExport.

    We pass the call to the underlying BatchExportSchedule. This exists here as a convinience so that users only
    need to interact with a BatchExport.
    """
    BatchExport.objects.filter(id=batch_export_id).update(paused=True)
    pause_schedule(temporal, schedule_id=batch_export_id, note=note)


@async_to_sync
async def pause_schedule(temporal: Client, schedule_id: str, note: str | None = None) -> None:
    """Pause a Temporal Schedule."""
    handle = temporal.get_schedule_handle(schedule_id)
    await handle.pause(note=note)


def unpause_batch_export(temporal: Client, batch_export_id: str, note: str | None = None) -> None:
    """Pause this BatchExport.

    We pass the call to the underlying BatchExportSchedule. This exists here as a convinience so that users only
    need to interact with a BatchExport.
    """
    BatchExport.objects.filter(id=batch_export_id).update(paused=False)
    unpause_schedule(temporal, schedule_id=batch_export_id, note=note)


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


def backfill_export(batch_export_id: str, start_at: dt.datetime | None = None, end_at: dt.datetime | None = None):
    """Creates an export run for the given BatchExport, and specified time range.
    Arguments:
        start_at: From when to backfill. If this is not defined, then we will backfill since this
            BatchExportSchedule's start_at.
        end_at: Up to when to backfill. If this is not defined, then we will backfill up to this
            BatchExportSchedule's created_at.
    """
    if start_at is None or end_at is None:
        raise ValidationError("start_at and end_at must be defined for backfilling")

    batch_export = BatchExport.objects.get(id=batch_export_id)
    backfill_run = BatchExportRun.objects.create(
        batch_export=batch_export,
        data_interval_start=start_at,
        data_interval_end=end_at,
    )
    (workflow, inputs) = DESTINATION_WORKFLOWS[batch_export.destination.type]
    temporal = sync_connect()
    temporal.execute_workflow(
        workflow,
        inputs(
            team_id=batch_export.pk,
            batch_export_id=batch_export_id,
            data_interval_end=end_at,
            **batch_export.destination.config,
        ),
        task_queue=settings.TEMPORAL_TASK_QUEUE,
        id=str(backfill_run.pk),
    )
    return backfill_run


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


def update_batch_export_run_status(run_id: UUID, status: str):
    """Update the status of an BatchExportRun with given id.

    Arguments:
        id: The id of the BatchExportRun to update.
    """
    updated = BatchExportRun.objects.filter(id=run_id).update(status=status)
    if not updated:
        raise ValueError(f"BatchExportRun with id {run_id} not found.")


def create_batch_export(team_id: int, interval: str, name: str, destination_data: dict):
    """
    Create a BatchExport and its underlying Schedule.
    """
    destination = BatchExportDestination.objects.create(**destination_data)

    batch_export = BatchExport.objects.create(team_id=team_id, name=name, interval=interval, destination=destination)

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
                intervals=[ScheduleIntervalSpec(every=time_delta_from_interval)],
            ),
            state=state,
        ),
        trigger_immediately=True,
    )

    return batch_export


async def acreate_batch_export(team_id: int, interval: str, name: str, destination_data: dict) -> BatchExport:
    """
    Create a BatchExport and its underlying Schedule.
    """
    return await sync_to_async(create_batch_export)(team_id, interval, name, destination_data)  # type: ignore


def fetch_batch_export_runs(batch_export_id: UUID, limit: int = 100) -> list[BatchExportRun]:
    """
    Fetch the BatchExportRuns for a given BatchExport.
    """
    return list(BatchExportRun.objects.filter(batch_export_id=batch_export_id).order_by("-created_at")[:limit])


async def afetch_batch_export_runs(batch_export_id: UUID, limit: int = 100) -> list[BatchExportRun]:
    """
    Fetch the BatchExportRuns for a given BatchExport.
    """
    return await sync_to_async(fetch_batch_export_runs)(batch_export_id, limit)  # type: ignore
