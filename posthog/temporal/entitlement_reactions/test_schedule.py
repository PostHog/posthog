from collections.abc import Awaitable, Callable

import pytest
from unittest.mock import AsyncMock, MagicMock

from temporalio.client import Client, ScheduleDescription, ScheduleState, ScheduleUpdate, ScheduleUpdateInput

from posthog.temporal.entitlement_reactions.schedule import create_entitlement_repair_schedule


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "paused,note",
    [(True, "Draining pending reactions"), (True, None), (False, None)],
)
async def test_schedule_update_preserves_operator_pause(paused: bool, note: str | None) -> None:
    description = MagicMock(
        spec=ScheduleDescription,
        schedule=MagicMock(state=ScheduleState(paused=paused, note=note)),
    )

    async def update(*, updater: Callable[[ScheduleUpdateInput], Awaitable[ScheduleUpdate | None]]) -> None:
        result = await updater(ScheduleUpdateInput(description=description))
        assert result is not None
        description.schedule = result.schedule

    client = MagicMock(spec=Client)
    handle = client.get_schedule_handle.return_value
    handle.describe = AsyncMock(return_value=description)
    handle.update = AsyncMock(side_effect=update)

    for _ in range(2):
        await create_entitlement_repair_schedule(client)
        assert description.schedule.state.paused is paused
        assert description.schedule.state.note == note
