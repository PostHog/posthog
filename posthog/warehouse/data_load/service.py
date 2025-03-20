from dataclasses import asdict
from datetime import timedelta
from typing import TYPE_CHECKING
from datetime import datetime

from temporalio.client import (
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleOverlapPolicy,
    SchedulePolicy,
    ScheduleSpec,
    ScheduleState,
    ScheduleCalendarSpec,
    ScheduleRange,
    ScheduleIntervalSpec,
)
from temporalio.common import RetryPolicy
from posthog.constants import DATA_WAREHOUSE_TASK_QUEUE
from posthog.temporal.common.client import async_connect, sync_connect
from posthog.temporal.common.schedule import (
    a_create_schedule,
    a_delete_schedule,
    a_trigger_schedule,
    a_update_schedule,
    create_schedule,
    pause_schedule,
    a_schedule_exists,
    schedule_exists,
    trigger_schedule,
    update_schedule,
    delete_schedule,
    unpause_schedule,
)
from posthog.temporal.utils import ExternalDataWorkflowInputs
import temporalio
from temporalio.client import Client as TemporalClient
from asgiref.sync import async_to_sync

from django.conf import settings
import s3fs

if TYPE_CHECKING:
    from posthog.warehouse.models import ExternalDataSource
    from posthog.warehouse.models.external_data_schema import ExternalDataSchema


def get_sync_schedule(external_data_schema: "ExternalDataSchema"):
    inputs = ExternalDataWorkflowInputs(
        team_id=external_data_schema.team_id,
        external_data_schema_id=external_data_schema.id,
        external_data_source_id=external_data_schema.source_id,
    )

    sync_frequency, jitter = get_sync_frequency(external_data_schema)

    hour = 0
    minute = 0
    # format 15:00:00 --> 3:00 PM UTC | default to midnight UTC
    if external_data_schema.sync_time_of_day:
        time_str = external_data_schema.sync_time_of_day
        time = datetime.strptime(str(time_str), "%H:%M:%S").time()
        hour = time.hour
        minute = time.minute

    return to_temporal_schedule(
        external_data_schema,
        inputs,
        hour_of_day=hour,
        minute_of_hour=minute,
        sync_frequency=sync_frequency,
        jitter=jitter,
    )


def to_temporal_schedule(
    external_data_schema, inputs, hour_of_day=0, minute_of_hour=0, sync_frequency=timedelta(hours=6), jitter=None
):
    action = ScheduleActionStartWorkflow(
        "external-data-job",
        asdict(inputs),
        id=str(external_data_schema.id),
        task_queue=str(DATA_WAREHOUSE_TASK_QUEUE),
        retry_policy=RetryPolicy(
            initial_interval=timedelta(seconds=10),
            maximum_interval=timedelta(seconds=60),
            maximum_attempts=3,
            non_retryable_error_types=["NondeterminismError"],
        ),
    )

    # Determine spec based on frequency
    if sync_frequency <= timedelta(hours=1):
        spec = ScheduleSpec(intervals=[ScheduleIntervalSpec(every=sync_frequency)], jitter=jitter)
    else:
        spec = ScheduleSpec(
            calendars=[get_calendar_spec(hour_of_day, minute_of_hour, sync_frequency)],
            jitter=jitter if minute_of_hour == 0 and hour_of_day == 0 else None,
        )

    return Schedule(
        action=action,
        spec=spec,
        state=ScheduleState(note=f"Schedule for external data source: {external_data_schema.pk}"),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
    )


def get_calendar_spec(hour_of_day: int, minute_of_hour: int, sync_frequency: timedelta) -> ScheduleCalendarSpec:
    hours_per_day = 24
    seconds_per_hour = 3600
    step = max(int(sync_frequency.total_seconds() // seconds_per_hour), 1)

    # If step is greater than or equal to 24 hours, we only need one execution per day
    if step >= hours_per_day:
        return ScheduleCalendarSpec(
            hour=[ScheduleRange(start=hour_of_day, end=hour_of_day, step=step)],
            minute=[ScheduleRange(start=minute_of_hour, end=minute_of_hour, step=1)],
        )

    end_hour = hour_of_day
    while (end_hour + step) < hours_per_day:
        end_hour += step

    return ScheduleCalendarSpec(
        hour=[ScheduleRange(start=hour_of_day, end=end_hour, step=step)],
        minute=[ScheduleRange(start=minute_of_hour, end=minute_of_hour, step=1)],
    )


def get_sync_frequency(external_data_schema: "ExternalDataSchema") -> tuple[timedelta, timedelta]:
    if external_data_schema.sync_frequency_interval <= timedelta(hours=1):
        return (external_data_schema.sync_frequency_interval, timedelta(minutes=1))
    if external_data_schema.sync_frequency_interval <= timedelta(hours=12):
        return (external_data_schema.sync_frequency_interval, timedelta(minutes=30))

    return (external_data_schema.sync_frequency_interval, timedelta(hours=1))


def sync_external_data_job_workflow(
    external_data_schema: "ExternalDataSchema", create: bool = False
) -> "ExternalDataSchema":
    temporal = sync_connect()

    schedule = get_sync_schedule(external_data_schema)

    if create:
        create_schedule(temporal, id=str(external_data_schema.id), schedule=schedule, trigger_immediately=True)
    else:
        update_schedule(temporal, id=str(external_data_schema.id), schedule=schedule)

    return external_data_schema


async def a_sync_external_data_job_workflow(
    external_data_schema: "ExternalDataSchema", create: bool = False
) -> "ExternalDataSchema":
    temporal = await async_connect()

    schedule = get_sync_schedule(external_data_schema)

    if create:
        await a_create_schedule(temporal, id=str(external_data_schema.id), schedule=schedule, trigger_immediately=True)
    else:
        await a_update_schedule(temporal, id=str(external_data_schema.id), schedule=schedule)

    return external_data_schema


def trigger_external_data_source_workflow(external_data_source: "ExternalDataSource"):
    temporal = sync_connect()
    trigger_schedule(temporal, schedule_id=str(external_data_source.id))


def trigger_external_data_workflow(external_data_schema: "ExternalDataSchema"):
    temporal = sync_connect()
    trigger_schedule(temporal, schedule_id=str(external_data_schema.id))


async def a_trigger_external_data_workflow(external_data_schema: "ExternalDataSchema"):
    temporal = await async_connect()
    await a_trigger_schedule(temporal, schedule_id=str(external_data_schema.id))


def external_data_workflow_exists(id: str) -> bool:
    temporal = sync_connect()
    return schedule_exists(temporal, schedule_id=id)


async def a_external_data_workflow_exists(id: str) -> bool:
    temporal = await async_connect()
    return await a_schedule_exists(temporal, schedule_id=id)


def pause_external_data_schedule(id: str):
    temporal = sync_connect()
    pause_schedule(temporal, schedule_id=id)


def unpause_external_data_schedule(id: str):
    temporal = sync_connect()
    unpause_schedule(temporal, schedule_id=id)


def delete_external_data_schedule(schedule_id: str):
    temporal = sync_connect()
    try:
        delete_schedule(temporal, schedule_id=schedule_id)
    except temporalio.service.RPCError as e:
        # Swallow error if schedule does not exist already
        if e.status == temporalio.service.RPCStatusCode.NOT_FOUND:
            return
        raise


async def a_delete_external_data_schedule(external_data_source: "ExternalDataSource"):
    temporal = await async_connect()
    try:
        await a_delete_schedule(temporal, schedule_id=str(external_data_source.id))
    except temporalio.service.RPCError as e:
        # Swallow error if schedule does not exist already
        if e.status == temporalio.service.RPCStatusCode.NOT_FOUND:
            return
        raise


def cancel_external_data_workflow(workflow_id: str):
    temporal = sync_connect()
    cancel_workflow(temporal, workflow_id)


@async_to_sync
async def cancel_workflow(temporal: TemporalClient, workflow_id: str):
    handle = temporal.get_workflow_handle(workflow_id)
    await handle.cancel()


def delete_data_import_folder(folder_path: str):
    s3 = s3fs.S3FileSystem(
        key=settings.AIRBYTE_BUCKET_KEY,
        secret=settings.AIRBYTE_BUCKET_SECRET,
    )
    bucket_name = settings.BUCKET_URL
    s3.delete(f"{bucket_name}/{folder_path}", recursive=True)


def is_any_external_data_schema_paused(team_id: int) -> bool:
    from posthog.warehouse.models import ExternalDataSchema

    return (
        ExternalDataSchema.objects.exclude(deleted=True)
        .filter(team_id=team_id, status=ExternalDataSchema.Status.PAUSED)
        .exists()
    )
