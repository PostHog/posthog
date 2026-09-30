import datetime as dt
from collections.abc import Awaitable, Callable

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from django.test import override_settings

from temporalio.client import Client, ScheduleActionStartWorkflow, ScheduleOverlapPolicy, ScheduleState

from products.alerts.backend.temporal.schedule import (
    INVENTORY_SCHEDULE_ID,
    SCHEDULE_ID,
    create_alerts_platform_inventory_schedule,
    create_alerts_platform_tick_schedule,
)

MODULE = "products.alerts.backend.temporal.schedule"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "create_schedule, schedule_id, workflow_name, execution_timeout",
    [
        (create_alerts_platform_tick_schedule, SCHEDULE_ID, "alerts-platform-orchestrate", dt.timedelta(seconds=50)),
        (
            create_alerts_platform_inventory_schedule,
            INVENTORY_SCHEDULE_ID,
            "alerts-platform-record-inventory",
            dt.timedelta(seconds=30),
        ),
    ],
)
@pytest.mark.parametrize("already_exists, paused", [(False, False), (True, False), (True, True)])
async def test_schedule_creates_or_updates_with_bounded_policy(
    create_schedule: Callable[[Client], Awaitable[None]],
    schedule_id: str,
    workflow_name: str,
    execution_timeout: dt.timedelta,
    already_exists: bool,
    paused: bool,
) -> None:
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
    assert action.execution_timeout == execution_timeout
    assert action.retry_policy is not None
    assert action.retry_policy.maximum_attempts == 1
    assert schedule.spec.cron_expressions == ["* * * * *"]
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
