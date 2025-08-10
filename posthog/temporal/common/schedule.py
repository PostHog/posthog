from asgiref.sync import async_to_sync
from temporalio.client import Client, Schedule, ScheduleUpdate, ScheduleUpdateInput, ScheduleOverlapPolicy


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
async def create_schedule(temporal: Client, id: str, schedule: Schedule, trigger_immediately: bool = False):
    """Create a Temporal Schedule."""
    return await temporal.create_schedule(
        id=id,
        schedule=schedule,
        trigger_immediately=trigger_immediately,
    )


async def a_create_schedule(temporal: Client, id: str, schedule: Schedule, trigger_immediately: bool = False):
    """Async create a Temporal Schedule."""
    return await temporal.create_schedule(
        id=id,
        schedule=schedule,
        trigger_immediately=trigger_immediately,
    )


@async_to_sync
async def update_schedule(temporal: Client, id: str, schedule: Schedule, keep_tz: bool = False) -> None:
    """Update a Temporal Schedule."""
    handle = temporal.get_schedule_handle(id)

    if keep_tz:
        desc = await handle.describe()
        schedule.spec.time_zone_name = desc.schedule.spec.time_zone_name

    async def updater(_: ScheduleUpdateInput) -> ScheduleUpdate:
        return ScheduleUpdate(schedule=schedule)

    return await handle.update(
        updater=updater,
    )


async def a_update_schedule(temporal: Client, id: str, schedule: Schedule) -> None:
    """Async update a Temporal Schedule."""
    handle = temporal.get_schedule_handle(id)

    async def updater(_: ScheduleUpdateInput) -> ScheduleUpdate:
        return ScheduleUpdate(schedule=schedule)

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
    """Check whether a schedule exists."""
    try:
        await temporal.get_schedule_handle(schedule_id).describe()
        return True
    except:
        return False


async def a_schedule_exists(temporal: Client, schedule_id: str) -> bool:
    """Check whether a schedule exists."""
    try:
        await temporal.get_schedule_handle(schedule_id).describe()
        return True
    except:
        return False
