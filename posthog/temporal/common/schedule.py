from __future__ import annotations

import asyncio
import functools
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, ParamSpec, TypeVar, cast

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

# tonic cancels a call that outruns the core client's per-request deadline and reports status
# CANCELLED with the message "Timeout expired". A transport connection that closes mid-request
# reports CANCELLED with "operation was canceled". Both describe the frontend, not the request, so
# match the message instead of the whole CANCELLED status, which would also swallow a real
# cancellation. The data imports client in products/warehouse_sources rides out the same pair.
TRANSIENT_CANCELLED_RPC_MESSAGES = ("Timeout expired", "operation was canceled")

RPC_MAX_ATTEMPTS = 3
RPC_INITIAL_BACKOFF_SECONDS = 0.5
RPC_BACKOFF_MULTIPLIER = 2.0


def is_transient_rpc_error(error: BaseException) -> bool:
    """Whether this error is a Temporal RPC failure that a later call can still get past."""
    if not isinstance(error, RPCError):
        return False
    if error.status in TRANSIENT_RPC_STATUS_CODES:
        return True
    return error.status == RPCStatusCode.CANCELLED and any(
        phrase in error.message for phrase in TRANSIENT_CANCELLED_RPC_MESSAGES
    )


def retry_transient_rpc(
    *, not_found_means_applied: bool = False
) -> Callable[[Callable[P, Awaitable[T]]], Callable[P, Awaitable[T]]]:
    """Retry a schedule call that failed on a transient Temporal RPC status.

    Only for calls a second attempt can repeat safely. Manual triggers are not: `handle.trigger()`
    takes no request id, so a retry past a lost response starts a second workflow run. Create is,
    because a landed first attempt makes the retry raise ScheduleAlreadyRunningError, which callers
    already read as "the schedule exists".

    `not_found_means_applied` closes the same gap for delete, whose landed first attempt leaves the
    retry nothing to find. Set it only where a NOT_FOUND raised on the very first attempt is the
    caller's business, because that one still propagates.
    """

    def already_applied(error: RPCError) -> bool:
        return not_found_means_applied and error.status == RPCStatusCode.NOT_FOUND

    def decorator(fn: Callable[P, Awaitable[T]]) -> Callable[P, Awaitable[T]]:
        @functools.wraps(fn)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            backoff = RPC_INITIAL_BACKOFF_SECONDS
            for attempt in range(1, RPC_MAX_ATTEMPTS):
                try:
                    return await fn(*args, **kwargs)
                except RPCError as error:
                    # past attempt 1 the call follows a transient failure, so a NOT_FOUND means the
                    # attempt that timed out landed after all
                    if attempt > 1 and already_applied(error):
                        return cast("T", None)
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
            try:
                return await fn(*args, **kwargs)
            except RPCError as error:
                if already_applied(error):
                    return cast("T", None)
                raise

        return wrapper

    return decorator


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
@retry_transient_rpc()
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


@retry_transient_rpc()
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
@retry_transient_rpc()
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


@retry_transient_rpc()
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
@retry_transient_rpc()
async def unpause_schedule(temporal: Client, schedule_id: str, note: str | None = None) -> None:
    """Unpause a Temporal Schedule."""
    handle = temporal.get_schedule_handle(schedule_id)
    await handle.unpause(note=note)


@async_to_sync
@retry_transient_rpc(not_found_means_applied=True)
async def delete_schedule(temporal: Client, schedule_id: str) -> None:
    """Delete a Temporal Schedule."""
    handle = temporal.get_schedule_handle(schedule_id)
    await handle.delete()


@retry_transient_rpc(not_found_means_applied=True)
async def a_delete_schedule(temporal: Client, schedule_id: str) -> None:
    """Async delete a Temporal Schedule."""
    handle = temporal.get_schedule_handle(schedule_id)
    await handle.delete()


@async_to_sync
@retry_transient_rpc()
async def describe_schedule(temporal: Client, schedule_id: str):
    """Describe a Temporal Schedule."""
    handle = temporal.get_schedule_handle(schedule_id)
    return await handle.describe()


@retry_transient_rpc()
async def a_describe_schedule(temporal: Client, schedule_id: str) -> ScheduleDescription:
    """Async describe a Temporal Schedule."""
    handle = temporal.get_schedule_handle(schedule_id)
    return await handle.describe()


@async_to_sync
@retry_transient_rpc()
async def pause_schedule(temporal: Client, schedule_id: str, note: str | None = None) -> None:
    """Pause a Temporal Schedule."""
    handle = temporal.get_schedule_handle(schedule_id)
    await handle.pause(note=note)


@retry_transient_rpc()
async def a_pause_schedule(temporal: Client, schedule_id: str, note: str | None = None) -> None:
    """Pause a Temporal Schedule."""
    handle = temporal.get_schedule_handle(schedule_id)
    await handle.pause(note=note)


@retry_transient_rpc()
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
@retry_transient_rpc()
async def schedule_exists(temporal: Client, schedule_id: str) -> bool:
    """Check whether a schedule exists."""
    try:
        await temporal.get_schedule_handle(schedule_id).describe()
        return True
    except RPCError as e:
        if e.status == RPCStatusCode.NOT_FOUND:
            return False
        raise


@retry_transient_rpc()
async def a_schedule_exists(temporal: Client, schedule_id: str) -> bool:
    """Check whether a schedule exists. See :func:`schedule_exists`."""
    try:
        await temporal.get_schedule_handle(schedule_id).describe()
        return True
    except RPCError as e:
        if e.status == RPCStatusCode.NOT_FOUND:
            return False
        raise
