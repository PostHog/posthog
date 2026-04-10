from __future__ import annotations

import random
from dataclasses import asdict
from datetime import UTC, datetime, time, timedelta
from typing import TYPE_CHECKING

from django.conf import settings

import temporalio
from asgiref.sync import async_to_sync
from temporalio.client import (
    Client as TemporalClient,
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleIntervalSpec,
    ScheduleOverlapPolicy,
    SchedulePolicy,
    ScheduleSpec,
    ScheduleState,
)
from temporalio.common import RetryPolicy

from posthog.temporal.common.client import async_connect, sync_connect
from posthog.temporal.common.schedule import (
    a_create_schedule,
    a_delete_schedule,
    a_schedule_exists,
    a_trigger_schedule,
    a_update_schedule,
    create_schedule,
    delete_schedule,
    pause_schedule,
    schedule_exists,
    trigger_schedule,
    unpause_schedule,
    update_schedule,
)
from posthog.temporal.utils import ExternalDataWorkflowInputs

if TYPE_CHECKING:
    from posthog.models import Team

    from products.data_warehouse.backend.models import ExternalDataSource
    from products.data_warehouse.backend.models.external_data_schema import ExternalDataSchema


def _jitter_timedelta(max_jitter: timedelta, rng: random.Random) -> tuple[int, int]:
    total_seconds = max_jitter.total_seconds()
    jitter_seconds = rng.uniform(0, total_seconds)

    return (int(jitter_seconds // 3600), int((jitter_seconds % 3600) // 60))


def get_sync_schedule(external_data_schema: ExternalDataSchema, should_sync: bool = True):
    inputs = ExternalDataWorkflowInputs(
        team_id=external_data_schema.team_id,
        external_data_schema_id=external_data_schema.id,
        external_data_source_id=external_data_schema.source_id,
    )

    hour = 0
    minute = 0
    sync_time_of_day: time | str | None = external_data_schema.sync_time_of_day
    # format 15:00:00 --> 3:00 PM UTC | default to midnight UTC
    if sync_time_of_day is not None:
        time_str = sync_time_of_day
        t = datetime.strptime(str(time_str), "%H:%M:%S").time()
        hour = t.hour
        minute = t.minute
    else:
        # Apply a one-time jitter based on the sync frequency to avoid all jobs syncing at the same time
        interval: timedelta | None = external_data_schema.sync_frequency_interval
        if interval is not None:
            rng = random.Random(str(external_data_schema.id))

            if interval <= timedelta(minutes=5):
                hour, minute = _jitter_timedelta(timedelta(minutes=5), rng)
            elif interval <= timedelta(minutes=30):
                hour, minute = _jitter_timedelta(timedelta(minutes=30), rng)
            elif interval <= timedelta(hours=1):
                hour, minute = _jitter_timedelta(timedelta(hours=1), rng)
            elif interval <= timedelta(hours=6):
                hour, minute = _jitter_timedelta(timedelta(hours=6), rng)
            elif interval <= timedelta(hours=12):
                hour, minute = _jitter_timedelta(timedelta(hours=12), rng)
            elif interval <= timedelta(days=1):
                hour, minute = _jitter_timedelta(timedelta(days=1), rng)

    return to_temporal_schedule(
        external_data_schema,
        inputs,
        hour_of_day=hour,
        minute_of_hour=minute,
        sync_frequency=external_data_schema.sync_frequency_interval,
        should_sync=should_sync,
    )


def to_temporal_schedule(
    external_data_schema,
    inputs,
    hour_of_day=0,
    minute_of_hour=0,
    sync_frequency=timedelta(hours=6),
    should_sync=True,
):
    action = ScheduleActionStartWorkflow(
        "external-data-job",
        asdict(inputs),
        id=str(external_data_schema.id),
        task_queue=str(settings.DATA_WAREHOUSE_TASK_QUEUE),
        retry_policy=RetryPolicy(
            initial_interval=timedelta(seconds=10),
            maximum_interval=timedelta(seconds=60),
            maximum_attempts=1,
            non_retryable_error_types=["NondeterminismError"],
        ),
    )

    sync_time = time(hour_of_day, minute_of_hour)
    schedule_start = datetime.combine(datetime.now(UTC).date(), sync_time, tzinfo=UTC)

    # Create the spec for the schedule based on the sync frequency and sync time
    # The sync time is applied using a combination of the offset and the start_at time
    spec = ScheduleSpec(
        intervals=[
            ScheduleIntervalSpec(
                every=sync_frequency,
                offset=timedelta(minutes=sync_time.hour * 60 + sync_time.minute) % sync_frequency,
            )
        ],
        start_at=schedule_start,
    )

    return Schedule(
        action=action,
        spec=spec,
        state=ScheduleState(
            paused=not should_sync,
            note=f"Schedule for external data schema: {external_data_schema.pk}",
        ),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
    )


def sync_external_data_job_workflow(
    external_data_schema: ExternalDataSchema, create: bool = False, should_sync: bool = True
) -> ExternalDataSchema:
    temporal = sync_connect()

    schedule = get_sync_schedule(external_data_schema, should_sync=should_sync)

    if create:
        create_schedule(temporal, id=str(external_data_schema.id), schedule=schedule, trigger_immediately=True)
    else:
        update_schedule(temporal, id=str(external_data_schema.id), schedule=schedule)

    return external_data_schema


async def a_sync_external_data_job_workflow(
    external_data_schema: ExternalDataSchema, create: bool = False, should_sync: bool = True
) -> ExternalDataSchema:
    temporal = await async_connect()

    schedule = get_sync_schedule(external_data_schema, should_sync=should_sync)

    if create:
        await a_create_schedule(temporal, id=str(external_data_schema.id), schedule=schedule, trigger_immediately=True)
    else:
        await a_update_schedule(temporal, id=str(external_data_schema.id), schedule=schedule)

    return external_data_schema


def trigger_external_data_source_workflow(external_data_source: ExternalDataSource):
    temporal = sync_connect()
    trigger_schedule(temporal, schedule_id=str(external_data_source.id))


def trigger_external_data_workflow(external_data_schema: ExternalDataSchema):
    temporal = sync_connect()
    trigger_schedule(temporal, schedule_id=str(external_data_schema.id))


async def a_trigger_external_data_workflow(external_data_schema: ExternalDataSchema):
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


async def a_delete_external_data_schedule(external_data_source: ExternalDataSource):
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


def is_any_external_data_schema_paused(team_id: int) -> bool:
    from products.data_warehouse.backend.models import ExternalDataSchema

    return (
        ExternalDataSchema.objects.exclude(deleted=True)
        .filter(team_id=team_id, status=ExternalDataSchema.Status.PAUSED)
        .exists()
    )


def is_cdc_enabled_for_team(team: Team) -> bool:
    """Check if the CDC feature flag is enabled for a team."""
    import posthoganalytics

    return posthoganalytics.feature_enabled(
        "dwh-postgres-cdc",
        str(team.uuid),
        groups={"organization": str(team.organization_id)},
        group_properties={"organization": {"id": str(team.organization_id)}},
    )


# ---------------------------------------------------------------------------
# CDC extraction scheduling (source-level)
# ---------------------------------------------------------------------------


def _get_cdc_extraction_schedule_id(source_id: str) -> str:
    return f"cdc-extraction-{source_id}"


def get_cdc_extraction_schedule(
    source: ExternalDataSource,
    min_interval: timedelta,
) -> Schedule:
    """Build a Temporal Schedule for the CDC extraction workflow.

    The schedule runs at the source level and the interval is the minimum
    sync_frequency_interval of all CDC-enabled schemas in the source.
    """
    from posthog.temporal.data_imports.cdc.workflows import CDCExtractionInput

    inputs = CDCExtractionInput(
        team_id=source.team_id,
        source_id=source.id,
    )

    action = ScheduleActionStartWorkflow(
        "cdc-extraction",
        asdict(inputs),
        id=_get_cdc_extraction_schedule_id(str(source.id)),
        task_queue=str(settings.DATA_WAREHOUSE_TASK_QUEUE),
        retry_policy=RetryPolicy(
            initial_interval=timedelta(seconds=10),
            maximum_interval=timedelta(seconds=120),
            maximum_attempts=3,
        ),
    )

    spec = ScheduleSpec(
        intervals=[ScheduleIntervalSpec(every=min_interval)],
    )

    return Schedule(
        action=action,
        spec=spec,
        state=ScheduleState(
            note=f"CDC extraction schedule for source: {source.id}",
        ),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
    )


def sync_cdc_extraction_schedule(source: ExternalDataSource, create: bool = False) -> None:
    """Create or update the CDC extraction Temporal schedule for a source.

    Calculates the interval from the most frequent CDC schema. If no CDC
    schemas are active, deletes the schedule.
    """
    from products.data_warehouse.backend.models import ExternalDataSchema

    cdc_schemas = list(
        ExternalDataSchema.objects.filter(
            source=source,
            sync_type=ExternalDataSchema.SyncType.CDC,
            should_sync=True,
        ).exclude(deleted=True)
    )

    schedule_id = _get_cdc_extraction_schedule_id(str(source.id))

    if not cdc_schemas:
        try:
            delete_external_data_schedule(schedule_id)
        except Exception:
            pass
        return

    intervals = [s.sync_frequency_interval for s in cdc_schemas if s.sync_frequency_interval is not None]
    min_interval = min(intervals) if intervals else timedelta(hours=1)

    temporal = sync_connect()
    schedule = get_cdc_extraction_schedule(source, min_interval)

    if create:
        create_schedule(temporal, id=schedule_id, schedule=schedule, trigger_immediately=True)
    else:
        try:
            update_schedule(temporal, id=schedule_id, schedule=schedule)
        except temporalio.service.RPCError as e:
            if e.status == temporalio.service.RPCStatusCode.NOT_FOUND:
                create_schedule(temporal, id=schedule_id, schedule=schedule, trigger_immediately=True)
            else:
                raise


def delete_cdc_extraction_schedule(source_id: str) -> None:
    """Delete the CDC extraction schedule for a source."""
    schedule_id = _get_cdc_extraction_schedule_id(source_id)
    try:
        delete_external_data_schedule(schedule_id)
    except Exception:
        pass


_CDC_SLOT_CLEANUP_SCHEDULE_ID = "cdc-slot-cleanup-global"


def ensure_cdc_slot_cleanup_schedule() -> None:
    """Ensure the global hourly CDCSlotCleanupWorkflow schedule exists.

    Idempotent — safe to call on every app startup or source creation.
    Creates the schedule if absent; no-ops if already present.
    """
    temporal = sync_connect()

    if schedule_exists(temporal, schedule_id=_CDC_SLOT_CLEANUP_SCHEDULE_ID):
        return

    action = ScheduleActionStartWorkflow(
        "cdc-slot-cleanup",
        id=_CDC_SLOT_CLEANUP_SCHEDULE_ID,
        task_queue=str(settings.DATA_WAREHOUSE_TASK_QUEUE),
        retry_policy=RetryPolicy(
            initial_interval=timedelta(seconds=30),
            maximum_interval=timedelta(seconds=300),
            maximum_attempts=2,
        ),
    )

    schedule = Schedule(
        action=action,
        spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=timedelta(hours=1))]),
        state=ScheduleState(note="Global CDC slot orphan cleanup and WAL lag monitor"),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
    )

    create_schedule(temporal, id=_CDC_SLOT_CLEANUP_SCHEDULE_ID, schedule=schedule)
