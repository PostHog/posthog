from __future__ import annotations

import random
import asyncio
from collections.abc import Iterable
from dataclasses import asdict
from datetime import UTC, datetime, time, timedelta
from typing import TYPE_CHECKING

from django.conf import settings

import structlog
import temporalio
from asgiref.sync import async_to_sync
from temporalio.client import (
    Client as TemporalClient,
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleAlreadyRunningError,
    ScheduleIntervalSpec,
    ScheduleOverlapPolicy,
    SchedulePolicy,
    ScheduleSpec,
    ScheduleState,
)
from temporalio.common import RetryPolicy

from posthog.ph_client import feature_enabled_or_false
from posthog.temporal.common.client import async_connect, sync_connect
from posthog.temporal.common.schedule import (
    a_create_schedule,
    a_delete_schedule,
    a_schedule_exists,
    a_trigger_schedule,
    a_unpause_schedule,
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

    from products.warehouse_sources.backend.facade.models import ExternalDataSchema, ExternalDataSource

logger = structlog.get_logger(__name__)


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
        try:
            create_schedule(temporal, id=str(external_data_schema.id), schedule=schedule, trigger_immediately=True)
        except ScheduleAlreadyRunningError:
            update_schedule(temporal, id=str(external_data_schema.id), schedule=schedule)
            trigger_schedule(temporal, schedule_id=str(external_data_schema.id))
    else:
        update_schedule(temporal, id=str(external_data_schema.id), schedule=schedule)

    return external_data_schema


async def a_sync_external_data_job_workflow(
    external_data_schema: ExternalDataSchema, create: bool = False, should_sync: bool = True
) -> ExternalDataSchema:
    temporal = await async_connect()

    schedule = get_sync_schedule(external_data_schema, should_sync=should_sync)

    if create:
        try:
            await a_create_schedule(
                temporal, id=str(external_data_schema.id), schedule=schedule, trigger_immediately=True
            )
        except ScheduleAlreadyRunningError:
            await a_update_schedule(temporal, id=str(external_data_schema.id), schedule=schedule)
            await a_trigger_schedule(temporal, schedule_id=str(external_data_schema.id))
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


async def a_unpause_external_data_schedule(id: str):
    temporal = await async_connect()
    await a_unpause_schedule(temporal, schedule_id=id)


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


# Bounded concurrency for bulk schedule operations. High enough to parallelise the
# per-RPC latency across thousands of schemas — each create_schedule with an immediate
# trigger is a relatively heavy server-side operation (it also starts a workflow) — but
# low enough to stay friendly to the Temporal frontend service.
_BULK_SCHEDULE_CONCURRENCY = 100


@async_to_sync
async def bulk_create_external_data_job_schedules(
    schemas: list[tuple[ExternalDataSchema, bool]],
) -> list[tuple[str, BaseException]]:
    """Create sync schedules for many schemas over a single shared Temporal connection.

    `sync_external_data_job_workflow` opens a fresh Temporal connection on every call, so
    looping it over thousands of schemas (e.g. a Slack workspace with thousands of
    channels) spends almost all of its time reconnecting. This connects once and runs the
    creates concurrently. Returns ``(schema_id, exception)`` pairs for any schedules that
    failed — a partial failure does not abort the rest, so the caller decides how to
    surface them and can attribute each failure to a specific schema.
    """
    if not schemas:
        return []

    temporal = await async_connect()
    semaphore = asyncio.Semaphore(_BULK_SCHEDULE_CONCURRENCY)

    async def _create_one(external_data_schema: ExternalDataSchema, should_sync: bool) -> None:
        async with semaphore:
            schedule = get_sync_schedule(external_data_schema, should_sync=should_sync)
            schedule_id = str(external_data_schema.id)
            try:
                await a_create_schedule(temporal, id=schedule_id, schedule=schedule, trigger_immediately=True)
            except ScheduleAlreadyRunningError:
                await a_update_schedule(temporal, id=schedule_id, schedule=schedule)
                await a_trigger_schedule(temporal, schedule_id=schedule_id)

    schema_ids = [str(schema.id) for schema, _ in schemas]
    results = await asyncio.gather(
        *(_create_one(schema, should_sync) for schema, should_sync in schemas),
        return_exceptions=True,
    )
    return [(schema_id, result) for schema_id, result in zip(schema_ids, results) if isinstance(result, BaseException)]


@async_to_sync
async def bulk_delete_external_data_schedules(schedule_ids: list[str]) -> list[tuple[str, BaseException]]:
    """Delete many Temporal schedules over a single shared connection.

    The bulk counterpart to `delete_external_data_schedule`: reuses one connection,
    deletes concurrently, and ignores schedules that no longer exist. Returns
    ``(schedule_id, exception)`` pairs for any deletes that failed for another reason.
    """
    if not schedule_ids:
        return []

    temporal = await async_connect()
    semaphore = asyncio.Semaphore(_BULK_SCHEDULE_CONCURRENCY)

    async def _delete_one(schedule_id: str) -> None:
        async with semaphore:
            try:
                await a_delete_schedule(temporal, schedule_id=schedule_id)
            except temporalio.service.RPCError as e:
                # Swallow error if schedule does not exist already
                if e.status == temporalio.service.RPCStatusCode.NOT_FOUND:
                    return
                raise

    results = await asyncio.gather(
        *(_delete_one(schedule_id) for schedule_id in schedule_ids),
        return_exceptions=True,
    )
    return [
        (schedule_id, result) for schedule_id, result in zip(schedule_ids, results) if isinstance(result, BaseException)
    ]


@async_to_sync
async def bulk_update_external_data_job_schedules(
    schemas: list[ExternalDataSchema],
) -> tuple[list[str], list[tuple[str, BaseException]]]:
    """Update (re-issue) sync schedules for many schemas over a single shared connection.

    The update-only counterpart to `bulk_create_external_data_job_schedules`: it connects
    once and updates concurrently, but never triggers a run and never creates a missing
    schedule. Schemas whose schedule does not exist (never activated) are reported as
    skipped rather than failed — matching the per-schema `sync_external_data_job_workflow`
    `create=False` path. Returns ``(skipped_ids, failures)``.
    """
    if not schemas:
        return [], []

    temporal = await async_connect()
    semaphore = asyncio.Semaphore(_BULK_SCHEDULE_CONCURRENCY)
    _SKIPPED = "skipped"

    async def _update_one(external_data_schema: ExternalDataSchema) -> str | None:
        async with semaphore:
            schedule = get_sync_schedule(external_data_schema, should_sync=external_data_schema.should_sync)
            try:
                await a_update_schedule(temporal, id=str(external_data_schema.id), schedule=schedule)
            except temporalio.service.RPCError as e:
                # No schedule yet (schema never activated) — skip, don't create.
                if e.status == temporalio.service.RPCStatusCode.NOT_FOUND:
                    return _SKIPPED
                raise
            return None

    schema_ids = [str(schema.id) for schema in schemas]
    results = await asyncio.gather(*(_update_one(schema) for schema in schemas), return_exceptions=True)
    skipped = [sid for sid, result in zip(schema_ids, results) if result == _SKIPPED]
    failures = [(sid, result) for sid, result in zip(schema_ids, results) if isinstance(result, BaseException)]
    return skipped, failures


def cancel_external_data_workflow(workflow_id: str):
    temporal = sync_connect()
    cancel_workflow(temporal, workflow_id)


@async_to_sync
async def cancel_workflow(temporal: TemporalClient, workflow_id: str):
    handle = temporal.get_workflow_handle(workflow_id)
    await handle.cancel()


def terminate_external_data_workflow(workflow_id: str, reason: str | None = None):
    temporal = sync_connect()
    terminate_workflow(temporal, workflow_id, reason=reason)


@async_to_sync
async def terminate_workflow(temporal: TemporalClient, workflow_id: str, reason: str | None = None):
    # Terminate, not cancel: cancellation is cooperative and needs a live worker to process the
    # request, so it can't clean up a run whose worker died (OOM, deploy, SIGKILL). Terminate is
    # forceful and server-side, which is what recovering an orphaned Running job requires.
    handle = temporal.get_workflow_handle(workflow_id)
    await handle.terminate(reason=reason)


def is_any_external_data_schema_paused(team_id: int) -> bool:
    from products.warehouse_sources.backend.facade.models import ExternalDataSchema

    return (
        ExternalDataSchema.objects.exclude(deleted=True)
        .filter(team_id=team_id, status=ExternalDataSchema.Status.PAUSED)
        .exists()
    )


def is_cdc_enabled_for_team(team: Team) -> bool:
    return feature_enabled_or_false(
        "dwh-postgres-cdc",
        str(team.organization_id),
        groups={"organization": str(team.organization_id)},
        group_properties={"organization": {"id": str(team.organization_id)}},
    )


def is_xmin_enabled_for_team(team: Team) -> bool:
    return feature_enabled_or_false(
        "dwh-postgres-xmin",
        str(team.organization_id),
        groups={"organization": str(team.organization_id)},
        group_properties={"organization": {"id": str(team.organization_id)}},
    )


def is_custom_source_ai_builder_enabled_for_team(team: Team) -> bool:
    return feature_enabled_or_false(
        "dwh-custom-source-ai-builder",
        str(team.organization_id),
        groups={"organization": str(team.organization_id)},
        group_properties={"organization": {"id": str(team.organization_id)}},
    )


# ---------------------------------------------------------------------------
# CDC extraction scheduling (source-level)
# ---------------------------------------------------------------------------


def _get_cdc_extraction_schedule_id(source_id: str) -> str:
    return f"cdc-extraction-{source_id}"


CDC_DEFAULT_INTERVAL = timedelta(hours=1)


def cdc_min_interval(sync_frequency_intervals: Iterable[timedelta | None]) -> timedelta:
    """CDC extraction interval for a source: the minimum sync frequency across its active CDC
    schemas, falling back to `CDC_DEFAULT_INTERVAL` when none declare one.

    Single source of truth shared by `sync_cdc_extraction_schedule` (per source) and the
    `backfill_cdc_extraction_schedules` command (batched), so the rule can't drift.
    """
    intervals = [interval for interval in sync_frequency_intervals if interval is not None]
    return min(intervals) if intervals else CDC_DEFAULT_INTERVAL


def get_cdc_extraction_schedule(
    source: ExternalDataSource,
    min_interval: timedelta,
) -> Schedule:
    """Build a Temporal Schedule for the CDC extraction workflow.

    The schedule runs at the source level and the interval is the minimum
    sync_frequency_interval of all CDC-enabled schemas in the source.
    """
    from products.warehouse_sources.backend.facade.pipelines import CDCExtractionInput

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
    from products.warehouse_sources.backend.facade.models import ExternalDataSchema

    # `source__deleted=True` is excluded so a deleted source (whose schemas may have been
    # left non-deleted by `soft_delete`) collapses to the "no active CDC schemas" branch below
    # and deletes its schedule rather than re-creating it.
    cdc_schemas = list(
        ExternalDataSchema.objects.filter(
            source=source,
            sync_type=ExternalDataSchema.SyncType.CDC,
            should_sync=True,
        )
        .exclude(deleted=True)
        .exclude(source__deleted=True)
    )

    schedule_id = _get_cdc_extraction_schedule_id(str(source.id))

    if not cdc_schemas:
        # No active CDC schemas left — dropping the schedule silently stops all CDC sync.
        logger.info(
            "Deleting CDC extraction schedule — no active CDC schemas",
            source_id=str(source.id),
            schedule_id=schedule_id,
        )
        try:
            delete_external_data_schedule(schedule_id)
        except Exception:
            logger.exception("Failed to delete CDC extraction schedule", schedule_id=schedule_id)
        return

    min_interval = cdc_min_interval(schema.sync_frequency_interval for schema in cdc_schemas)

    temporal = sync_connect()
    schedule = get_cdc_extraction_schedule(source, min_interval)

    logger.info(
        "Syncing CDC extraction schedule",
        source_id=str(source.id),
        schedule_id=schedule_id,
        create=create,
        cdc_schema_count=len(cdc_schemas),
        min_interval_seconds=min_interval.total_seconds(),
    )

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


def pause_cdc_extraction_schedule(source_id: str) -> None:
    """Pause the CDC extraction schedule for a source so it stops firing.

    Used when CDC is marked broken (e.g. the safety net dropped the slot): leaving the
    schedule running would retry forever against a slot that no longer exists. A missing
    schedule is treated as a no-op.
    """
    schedule_id = _get_cdc_extraction_schedule_id(source_id)
    temporal = sync_connect()
    try:
        pause_schedule(temporal, schedule_id=schedule_id)
    except temporalio.service.RPCError as e:
        if e.status == temporalio.service.RPCStatusCode.NOT_FOUND:
            return
        raise


@async_to_sync
async def bulk_sync_cdc_extraction_schedules(
    source_intervals: list[tuple[ExternalDataSource, timedelta]],
) -> list[tuple[str, BaseException]]:
    """Upsert CDC extraction schedules for many sources over a single shared connection.

    The bulk counterpart to `sync_cdc_extraction_schedule`: connects once and upserts
    concurrently. The caller must compute each ``(source, min_interval)`` pair synchronously
    (the per-source interval needs a DB query that can't run in this async context). Returns
    ``(source_id, exception)`` pairs for any that failed — a partial failure does not abort
    the rest.
    """
    if not source_intervals:
        return []

    temporal = await async_connect()
    semaphore = asyncio.Semaphore(_BULK_SCHEDULE_CONCURRENCY)

    async def _sync_one(source: ExternalDataSource, min_interval: timedelta) -> None:
        async with semaphore:
            schedule_id = _get_cdc_extraction_schedule_id(str(source.id))
            schedule = get_cdc_extraction_schedule(source, min_interval)
            try:
                await a_update_schedule(temporal, id=schedule_id, schedule=schedule)
            except temporalio.service.RPCError as e:
                if e.status == temporalio.service.RPCStatusCode.NOT_FOUND:
                    await a_create_schedule(temporal, id=schedule_id, schedule=schedule, trigger_immediately=True)
                else:
                    raise

    source_ids = [str(source.id) for source, _ in source_intervals]
    results = await asyncio.gather(
        *(_sync_one(source, interval) for source, interval in source_intervals),
        return_exceptions=True,
    )
    return [(source_id, result) for source_id, result in zip(source_ids, results) if isinstance(result, BaseException)]


# ---------------------------------------------------------------------------
# Schema discovery scheduling (source-level)
# ---------------------------------------------------------------------------

DISCOVER_SCHEMAS_INTERVAL = timedelta(hours=6)


def _get_discover_schemas_schedule_id(source_id: str) -> str:
    return f"discover-schemas-{source_id}"


def get_discover_schemas_schedule(source: ExternalDataSource) -> Schedule:
    """Build a Temporal Schedule for the per-source schema-discovery workflow."""
    # Inline import breaks a circular dependency: `sync_new_schemas` needs
    # `delete_external_data_schedule` and `_get_discover_schemas_schedule_id` from this
    # module for self-cleanup when the source vanishes, so it imports from us at module
    # load time. Hoisting this import would deadlock the loader.
    from products.warehouse_sources.backend.facade.pipelines import SyncNewSchemasActivityInputs

    inputs = SyncNewSchemasActivityInputs(source_id=str(source.id), team_id=source.team_id)

    action = ScheduleActionStartWorkflow(
        "discover-schemas",
        asdict(inputs),
        id=_get_discover_schemas_schedule_id(str(source.id)),
        task_queue=str(settings.DATA_WAREHOUSE_TASK_QUEUE),
        retry_policy=RetryPolicy(
            initial_interval=timedelta(seconds=10),
            maximum_interval=timedelta(seconds=60),
            maximum_attempts=3,
            non_retryable_error_types=["NondeterminismError"],
        ),
    )

    # Deterministic per-source offset so sources sharing a cadence don't dogpile.
    offset_hours, offset_minutes = _jitter_timedelta(DISCOVER_SCHEMAS_INTERVAL, random.Random(str(source.id)))
    spec = ScheduleSpec(
        intervals=[
            ScheduleIntervalSpec(
                every=DISCOVER_SCHEMAS_INTERVAL,
                offset=timedelta(hours=offset_hours, minutes=offset_minutes),
            )
        ],
    )

    return Schedule(
        action=action,
        spec=spec,
        state=ScheduleState(note=f"Discover schemas schedule for source: {source.id}"),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
    )


def sync_discover_schemas_schedule(source: ExternalDataSource, create: bool = False) -> None:
    """Create or update the per-source schema-discovery Temporal schedule.

    On ``create=True`` triggers an immediate run so a brand-new source picks up
    its initial schema list right away. On ``create=False`` (or when the
    schedule turns out not to exist), upserts idempotently — this makes the
    helper safe for both fresh deploys and the backfill management command.
    """
    temporal = sync_connect()
    schedule_id = _get_discover_schemas_schedule_id(str(source.id))
    schedule = get_discover_schemas_schedule(source)

    if create:
        create_schedule(temporal, id=schedule_id, schedule=schedule, trigger_immediately=True)
        return

    try:
        update_schedule(temporal, id=schedule_id, schedule=schedule)
    except temporalio.service.RPCError as e:
        if e.status == temporalio.service.RPCStatusCode.NOT_FOUND:
            create_schedule(temporal, id=schedule_id, schedule=schedule, trigger_immediately=True)
        else:
            raise


@async_to_sync
async def bulk_sync_discover_schemas_schedules(
    sources: list[ExternalDataSource],
) -> list[tuple[str, BaseException]]:
    """Upsert discover-schemas schedules for many sources over a single shared connection.

    `sync_discover_schemas_schedule` opens a fresh Temporal connection on every call, so
    looping it over thousands of sources (e.g. a backfill) spends almost all of its time
    reconnecting. This connects once and runs the upserts concurrently. Returns
    ``(source_id, exception)`` pairs for any schedules that failed — a partial failure does
    not abort the rest, so the caller can attribute each failure to a specific source.
    """
    if not sources:
        return []

    temporal = await async_connect()
    semaphore = asyncio.Semaphore(_BULK_SCHEDULE_CONCURRENCY)

    async def _sync_one(source: ExternalDataSource) -> None:
        async with semaphore:
            schedule_id = _get_discover_schemas_schedule_id(str(source.id))
            schedule = get_discover_schemas_schedule(source)
            try:
                await a_update_schedule(temporal, id=schedule_id, schedule=schedule)
            except temporalio.service.RPCError as e:
                if e.status == temporalio.service.RPCStatusCode.NOT_FOUND:
                    await a_create_schedule(temporal, id=schedule_id, schedule=schedule, trigger_immediately=True)
                else:
                    raise

    source_ids = [str(source.id) for source in sources]
    results = await asyncio.gather(*(_sync_one(source) for source in sources), return_exceptions=True)
    return [(source_id, result) for source_id, result in zip(source_ids, results) if isinstance(result, BaseException)]


def delete_discover_schemas_schedule(source_id: str) -> None:
    schedule_id = _get_discover_schemas_schedule_id(source_id)
    try:
        delete_external_data_schedule(schedule_id)
    except Exception:
        # delete_external_data_schedule already swallows NOT_FOUND; defensively
        # ignore other races (e.g. schedule deleted between fetch and delete).
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
