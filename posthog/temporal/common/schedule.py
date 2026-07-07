from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import structlog
from asgiref.sync import async_to_sync
from temporalio.client import Client, Schedule, ScheduleOverlapPolicy, ScheduleUpdate, ScheduleUpdateInput
from temporalio.service import RPCError, RPCStatusCode

if TYPE_CHECKING:
    from temporalio.common import TypedSearchAttributes

logger = structlog.get_logger(__name__)

# gRPC statuses that indicate a transient blip (deadline hit, server briefly
# unavailable, request cancelled/rate-limited) rather than a real answer about
# whether the schedule exists. A `describe()` that fails with one of these is
# worth retrying — client-side call timeouts surface as CANCELLED ("Timeout
# expired") or DEADLINE_EXCEEDED.
_TRANSIENT_RPC_STATUS_CODES = frozenset(
    {
        RPCStatusCode.CANCELLED,
        RPCStatusCode.DEADLINE_EXCEEDED,
        RPCStatusCode.UNAVAILABLE,
        RPCStatusCode.RESOURCE_EXHAUSTED,
        RPCStatusCode.ABORTED,
    }
)

_SCHEDULE_EXISTS_MAX_ATTEMPTS = 3
_SCHEDULE_EXISTS_BACKOFF_SECONDS = 0.5


@async_to_sync
async def trigger_schedule_buffer_one(temporal: Client, schedule_id: str):
    """Trigger a Temporal Schedule using BUFFER_ONE overlap policy."""
    return await a_trigger_schedule_buffer_one(temporal, schedule_id)


async def a_trigger_schedule_buffer_one(temporal: Client, schedule_id: str):
    """Async trigger a Temporal Schedule using BUFFER_ONE overlap policy."""
    handle = temporal.get_schedule_handle(schedule_id)
    await handle.trigger(
        overlap=ScheduleOverlapPolicy.BUFFER_ONE,
    )


@async_to_sync
async def create_schedule(
    temporal: Client,
    id: str,
    schedule: Schedule,
    trigger_immediately: bool = False,
    search_attributes: TypedSearchAttributes | None = None,
):
    """Create a Temporal Schedule."""
    return await temporal.create_schedule(
        id=id,
        schedule=schedule,
        trigger_immediately=trigger_immediately,
        search_attributes=search_attributes,
    )


async def a_create_schedule(
    temporal: Client,
    id: str,
    schedule: Schedule,
    trigger_immediately: bool = False,
    search_attributes: TypedSearchAttributes | None = None,
):
    """Async create a Temporal Schedule."""
    return await temporal.create_schedule(
        id=id,
        schedule=schedule,
        trigger_immediately=trigger_immediately,
        search_attributes=search_attributes,
    )


@async_to_sync
async def update_schedule(
    temporal: Client,
    id: str,
    schedule: Schedule,
    keep_tz: bool = False,
    search_attributes: TypedSearchAttributes | None = None,
) -> None:
    """Update a Temporal Schedule."""
    handle = temporal.get_schedule_handle(id)

    if keep_tz:
        desc = await handle.describe()
        schedule.spec.time_zone_name = desc.schedule.spec.time_zone_name

    async def updater(_: ScheduleUpdateInput) -> ScheduleUpdate:
        return ScheduleUpdate(schedule=schedule, search_attributes=search_attributes)

    return await handle.update(
        updater=updater,
    )


async def a_update_schedule(
    temporal: Client,
    id: str,
    schedule: Schedule,
    search_attributes: TypedSearchAttributes | None = None,
) -> None:
    """Async update a Temporal Schedule."""
    handle = temporal.get_schedule_handle(id)

    async def updater(_: ScheduleUpdateInput) -> ScheduleUpdate:
        return ScheduleUpdate(schedule=schedule, search_attributes=search_attributes)

    return await handle.update(
        updater=updater,
    )


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


async def a_delete_schedule(temporal: Client, schedule_id: str) -> None:
    """Async delete a Temporal Schedule."""
    handle = temporal.get_schedule_handle(schedule_id)
    await handle.delete()


@async_to_sync
async def describe_schedule(temporal: Client, schedule_id: str):
    """Describe a Temporal Schedule."""
    handle = temporal.get_schedule_handle(schedule_id)
    return await handle.describe()


@async_to_sync
async def pause_schedule(temporal: Client, schedule_id: str, note: str | None = None) -> None:
    """Pause a Temporal Schedule."""
    handle = temporal.get_schedule_handle(schedule_id)
    await handle.pause(note=note)


async def a_pause_schedule(temporal: Client, schedule_id: str, note: str | None = None) -> None:
    """Pause a Temporal Schedule."""
    handle = temporal.get_schedule_handle(schedule_id)
    await handle.pause(note=note)


async def a_unpause_schedule(temporal: Client, schedule_id: str, note: str | None = None) -> None:
    """Unpause a Temporal Schedule."""
    handle = temporal.get_schedule_handle(schedule_id)
    await handle.unpause(note=note)


@async_to_sync
async def trigger_schedule(temporal: Client, schedule_id: str, note: str | None = None) -> None:
    """Trigger a Temporal Schedule."""
    handle = temporal.get_schedule_handle(schedule_id)
    await handle.trigger()


async def a_trigger_schedule(temporal: Client, schedule_id: str, note: str | None = None) -> None:
    """Trigger a Temporal Schedule."""
    handle = temporal.get_schedule_handle(schedule_id)
    await handle.trigger()


@async_to_sync
async def schedule_exists(temporal: Client, schedule_id: str) -> bool:
    """Check whether a schedule exists. See :func:`a_schedule_exists`."""
    return await a_schedule_exists(temporal, schedule_id)


async def a_schedule_exists(temporal: Client, schedule_id: str) -> bool:
    """Check whether a schedule exists.

    NOT_FOUND is the definitive "no". Transient RPC failures (call timeouts,
    server temporarily unavailable) are retried a few times with a short backoff
    so a Temporal blip doesn't fail a caller running this check inline on a
    user-facing request path.
    """
    last_error: RPCError | None = None
    for attempt in range(_SCHEDULE_EXISTS_MAX_ATTEMPTS):
        try:
            await temporal.get_schedule_handle(schedule_id).describe()
            return True
        except RPCError as e:
            if e.status == RPCStatusCode.NOT_FOUND:
                return False
            if e.status not in _TRANSIENT_RPC_STATUS_CODES:
                raise
            last_error = e
            if attempt < _SCHEDULE_EXISTS_MAX_ATTEMPTS - 1:
                logger.warning(
                    "Transient RPC error checking schedule existence, retrying",
                    schedule_id=schedule_id,
                    attempt=attempt + 1,
                    status=e.status.name,
                )
                await asyncio.sleep(_SCHEDULE_EXISTS_BACKOFF_SECONDS * (attempt + 1))

    assert last_error is not None
    raise last_error
