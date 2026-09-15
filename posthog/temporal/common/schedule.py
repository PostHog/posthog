from __future__ import annotations

import asyncio
import functools
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, ParamSpec, TypeVar

import structlog
from asgiref.sync import async_to_sync
from temporalio.client import (
    Client,
    Schedule,
    ScheduleDescription,
    ScheduleOverlapPolicy,
    ScheduleUpdate,
    ScheduleUpdateInput,
)
from temporalio.service import RPCError, RPCStatusCode

if TYPE_CHECKING:
    from temporalio.common import TypedSearchAttributes

logger = structlog.get_logger(__name__)

P = ParamSpec("P")
T = TypeVar("T")

# Statuses where the schedule operation may well succeed on a second try: the Temporal frontend was
# slow, busy, restarting, or lost the connection. Everything else (NOT_FOUND, ALREADY_EXISTS,
# INVALID_ARGUMENT, PERMISSION_DENIED) describes the request, so a retry would only repeat it.
TRANSIENT_RPC_STATUS_CODES = frozenset(
    {
        RPCStatusCode.DEADLINE_EXCEEDED,
        RPCStatusCode.UNAVAILABLE,
        RPCStatusCode.RESOURCE_EXHAUSTED,
        RPCStatusCode.ABORTED,
        RPCStatusCode.INTERNAL,
        RPCStatusCode.UNKNOWN,
    }
)

RPC_MAX_ATTEMPTS = 3
RPC_INITIAL_BACKOFF_SECONDS = 0.5
RPC_BACKOFF_MULTIPLIER = 2.0


def is_transient_rpc_error(error: BaseException) -> bool:
    """Whether this error is a Temporal RPC failure that a later call can still get past."""
    return isinstance(error, RPCError) and error.status in TRANSIENT_RPC_STATUS_CODES


def retry_transient_rpc(fn: Callable[P, Awaitable[T]]) -> Callable[P, Awaitable[T]]:
    """Retry a schedule call that failed on a transient Temporal RPC status.

    Every helper here is idempotent for the same inputs, apart from create, which raises
    ScheduleAlreadyRunningError when an earlier attempt landed after all. Callers already treat
    that as "the schedule exists", so the retry cannot silently duplicate a schedule.
    """

    @functools.wraps(fn)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
        backoff = RPC_INITIAL_BACKOFF_SECONDS
        for attempt in range(1, RPC_MAX_ATTEMPTS):
            try:
                return await fn(*args, **kwargs)
            except RPCError as error:
                if not is_transient_rpc_error(error):
                    raise
                logger.warning(
                    "Retrying Temporal schedule call after a transient RPC failure",
                    operation=fn.__name__,
                    status=error.status.name,
                    attempt=attempt,
                    max_attempts=RPC_MAX_ATTEMPTS,
                )
                await asyncio.sleep(backoff)
                backoff *= RPC_BACKOFF_MULTIPLIER
        return await fn(*args, **kwargs)

    return wrapper


@async_to_sync
async def trigger_schedule_buffer_one(temporal: Client, schedule_id: str):
    """Trigger a Temporal Schedule using BUFFER_ONE overlap policy."""
    return await a_trigger_schedule_buffer_one(temporal, schedule_id)


@retry_transient_rpc
async def a_trigger_schedule_buffer_one(temporal: Client, schedule_id: str):
    """Async trigger a Temporal Schedule using BUFFER_ONE overlap policy."""
    handle = temporal.get_schedule_handle(schedule_id)
    await handle.trigger(
        overlap=ScheduleOverlapPolicy.BUFFER_ONE,
    )


@async_to_sync
@retry_transient_rpc
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


@retry_transient_rpc
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
@retry_transient_rpc
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


@retry_transient_rpc
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
@retry_transient_rpc
async def unpause_schedule(temporal: Client, schedule_id: str, note: str | None = None) -> None:
    """Unpause a Temporal Schedule."""
    handle = temporal.get_schedule_handle(schedule_id)
    await handle.unpause(note=note)


@async_to_sync
@retry_transient_rpc
async def delete_schedule(temporal: Client, schedule_id: str) -> None:
    """Delete a Temporal Schedule."""
    handle = temporal.get_schedule_handle(schedule_id)
    await handle.delete()


@retry_transient_rpc
async def a_delete_schedule(temporal: Client, schedule_id: str) -> None:
    """Async delete a Temporal Schedule."""
    handle = temporal.get_schedule_handle(schedule_id)
    await handle.delete()


@async_to_sync
@retry_transient_rpc
async def describe_schedule(temporal: Client, schedule_id: str):
    """Describe a Temporal Schedule."""
    handle = temporal.get_schedule_handle(schedule_id)
    return await handle.describe()


@retry_transient_rpc
async def a_describe_schedule(temporal: Client, schedule_id: str) -> ScheduleDescription:
    """Async describe a Temporal Schedule."""
    handle = temporal.get_schedule_handle(schedule_id)
    return await handle.describe()


@async_to_sync
@retry_transient_rpc
async def pause_schedule(temporal: Client, schedule_id: str, note: str | None = None) -> None:
    """Pause a Temporal Schedule."""
    handle = temporal.get_schedule_handle(schedule_id)
    await handle.pause(note=note)


@retry_transient_rpc
async def a_pause_schedule(temporal: Client, schedule_id: str, note: str | None = None) -> None:
    """Pause a Temporal Schedule."""
    handle = temporal.get_schedule_handle(schedule_id)
    await handle.pause(note=note)


@retry_transient_rpc
async def a_unpause_schedule(temporal: Client, schedule_id: str, note: str | None = None) -> None:
    """Unpause a Temporal Schedule."""
    handle = temporal.get_schedule_handle(schedule_id)
    await handle.unpause(note=note)


@async_to_sync
@retry_transient_rpc
async def trigger_schedule(temporal: Client, schedule_id: str, note: str | None = None) -> None:
    """Trigger a Temporal Schedule."""
    handle = temporal.get_schedule_handle(schedule_id)
    await handle.trigger()


@retry_transient_rpc
async def a_trigger_schedule(temporal: Client, schedule_id: str, note: str | None = None) -> None:
    """Trigger a Temporal Schedule."""
    handle = temporal.get_schedule_handle(schedule_id)
    await handle.trigger()


@async_to_sync
@retry_transient_rpc
async def schedule_exists(temporal: Client, schedule_id: str) -> bool:
    """Check whether a schedule exists."""
    try:
        await temporal.get_schedule_handle(schedule_id).describe()
        return True
    except RPCError as e:
        if e.status == RPCStatusCode.NOT_FOUND:
            return False
        raise


@retry_transient_rpc
async def a_schedule_exists(temporal: Client, schedule_id: str) -> bool:
    """Check whether a schedule exists. See :func:`schedule_exists`."""
    try:
        await temporal.get_schedule_handle(schedule_id).describe()
        return True
    except RPCError as e:
        if e.status == RPCStatusCode.NOT_FOUND:
            return False
        raise
