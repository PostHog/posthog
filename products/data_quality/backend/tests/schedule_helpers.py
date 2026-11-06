from collections.abc import Callable
from copy import deepcopy
from datetime import UTC, datetime, timedelta

from unittest.mock import AsyncMock, Mock

from temporalio.client import (
    Schedule,
    ScheduleAlreadyRunningError,
    ScheduleDescription,
    ScheduleUpdate,
    ScheduleUpdateInput,
)
from temporalio.service import RPCError, RPCStatusCode


def schedule_client() -> Mock:
    client = Mock()
    schedules: dict[str, Schedule] = {}
    client.schedules = schedules

    async def create(*, id: str, schedule: Schedule, **kwargs: object) -> None:
        if id in schedules:
            raise ScheduleAlreadyRunningError()
        schedules[id] = deepcopy(schedule)

    def handle(schedule_id: str) -> Mock:
        async def describe() -> Mock:
            if schedule_id not in schedules:
                raise RPCError("Schedule missing", RPCStatusCode.NOT_FOUND, b"")
            return Mock(
                spec=ScheduleDescription,
                schedule=deepcopy(schedules[schedule_id]),
                info=Mock(next_action_times=[datetime.now(UTC) + timedelta(hours=1)]),
            )

        async def update(callback: Callable[[ScheduleUpdateInput], ScheduleUpdate]) -> None:
            result = callback(ScheduleUpdateInput(description=await describe()))
            schedules[schedule_id] = result.schedule

        async def delete() -> None:
            schedules.pop(schedule_id, None)

        return Mock(
            describe=AsyncMock(side_effect=describe),
            update=AsyncMock(side_effect=update),
            delete=AsyncMock(side_effect=delete),
        )

    client.create_schedule = AsyncMock(side_effect=create)
    client.get_schedule_handle.side_effect = handle
    return client
