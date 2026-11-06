import datetime as dt
from collections.abc import Awaitable, Callable

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from django.test import override_settings

from temporalio.client import Client, ScheduleActionStartWorkflow, ScheduleOverlapPolicy, ScheduleState
from temporalio.common import Priority

from products.alerts_platform.backend.temporal.schedule import (
    INVENTORY_SCHEDULE_ID,
    SCHEDULE_ID,
    create_alerts_platform_inventory_schedule,
    create_alerts_platform_tick_schedule,
)

MODULE = "products.alerts_platform.backend.temporal.schedule"


TICK = (create_alerts_platform_tick_schedule, SCHEDULE_ID, "alerts-platform-orchestrate", "* * * * *", 50, Priority())
INVENTORY = (
    create_alerts_platform_inventory_schedule,
    INVENTORY_SCHEDULE_ID,
    "alerts-platform-record-inventory",
    "*/5 * * * *",
    30,
    Priority(priority_key=5),
)


@pytest.mark.asyncio
@pytest.mark.parametrize("target", [TICK, INVENTORY], ids=["tick", "inventory"])
@pytest.mark.parametrize("already_exists, paused", [(False, False), (True, False), (True, True)])
async def test_schedule_creates_or_updates_with_bounded_policy(
    already_exists: bool,
    paused: bool,
    target: tuple[Callable[[Client], Awaitable[None]], str, str, str, int, Priority],
) -> None:
    create_schedule, schedule_id, workflow_name, cron, timeout_seconds, priority = target
    client = MagicMock(spec=Client)
    state = ScheduleState(paused=paused, note="Operator-controlled state")
    client.get_schedule_handle.return_value.describe = AsyncMock(
        return_value=MagicMock(schedule=MagicMock(state=state))
    )
    with (
        override_settings(
            # A non-DEV deployment, because DEV would pass even if a region gate returned early.
            CLOUD_DEPLOYMENT="US",
            ALERTS_PLATFORM_SHARED_ORCHESTRATION_TASK_QUEUE="orchestration-test-queue",
        ),
        patch(f"{MODULE}.a_schedule_exists", return_value=already_exists) as exists,
        patch(f"{MODULE}.a_create_schedule") as create,
        patch(f"{MODULE}.a_update_schedule") as update,
    ):
        await create_schedule(client)

    exists.assert_awaited_once_with(client, schedule_id)
    called = update if already_exists else create
    unused = create if already_exists else update
    called.assert_awaited_once()
    unused.assert_not_awaited()
    assert called.await_args is not None
    assert called.await_args.args[:2] == (client, schedule_id)
    assert called.await_args.kwargs == ({} if already_exists else {"trigger_immediately": False})
    schedule = called.await_args.args[2]
    action = schedule.action
    assert isinstance(action, ScheduleActionStartWorkflow)
    assert action.workflow == workflow_name
    assert list(action.args) == [{}]
    assert action.id == schedule_id
    assert action.task_queue == "orchestration-test-queue"
    assert action.execution_timeout == dt.timedelta(seconds=timeout_seconds)
    assert action.priority == priority
    assert action.retry_policy is not None
    assert action.retry_policy.maximum_attempts == 1
    assert schedule.spec.cron_expressions == [cron]
    assert schedule.policy.overlap == ScheduleOverlapPolicy.SKIP
    assert schedule.policy.catchup_window == dt.timedelta(minutes=1)
    assert not schedule.policy.pause_on_failure
    assert schedule.state.paused is paused
    if already_exists:
        client.get_schedule_handle.assert_called_once_with(schedule_id)
        client.get_schedule_handle.return_value.describe.assert_awaited_once()
        assert schedule.state == state
    else:
        client.get_schedule_handle.assert_not_called()
