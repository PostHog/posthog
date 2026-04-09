import datetime as dt

import pytest
from unittest.mock import AsyncMock, patch

from temporalio.client import Schedule, ScheduleActionStartWorkflow, ScheduleOverlapPolicy, ScheduleSpec

from posthog.temporal.alerts.schedule import create_schedule_due_alert_checks_schedule


def test_schedule_is_registered_in_init_schedules():
    from posthog.temporal.schedule import schedules

    assert create_schedule_due_alert_checks_schedule in schedules


@pytest.mark.asyncio
async def test_create_schedule_creates_when_absent():
    mock_client = AsyncMock()
    with (
        patch(
            "posthog.temporal.alerts.schedule.a_schedule_exists",
            new=AsyncMock(return_value=False),
        ),
        patch(
            "posthog.temporal.alerts.schedule.a_create_schedule",
            new=AsyncMock(),
        ) as mock_create,
        patch(
            "posthog.temporal.alerts.schedule.a_update_schedule",
            new=AsyncMock(),
        ) as mock_update,
    ):
        await create_schedule_due_alert_checks_schedule(mock_client)

    mock_create.assert_awaited_once()
    mock_update.assert_not_awaited()

    call_args = mock_create.await_args
    assert call_args is not None
    schedule_arg = call_args.args[2]
    assert isinstance(schedule_arg, Schedule)
    assert isinstance(schedule_arg.spec, ScheduleSpec)
    assert schedule_arg.spec.cron_expressions == ["*/2 * * * *"]
    assert schedule_arg.policy.overlap == ScheduleOverlapPolicy.ALLOW_ALL
    assert isinstance(schedule_arg.action, ScheduleActionStartWorkflow)
    assert schedule_arg.action.execution_timeout == dt.timedelta(minutes=10)
    assert call_args.kwargs.get("trigger_immediately") is False


@pytest.mark.asyncio
async def test_create_schedule_updates_when_present():
    mock_client = AsyncMock()
    with (
        patch(
            "posthog.temporal.alerts.schedule.a_schedule_exists",
            new=AsyncMock(return_value=True),
        ),
        patch(
            "posthog.temporal.alerts.schedule.a_create_schedule",
            new=AsyncMock(),
        ) as mock_create,
        patch(
            "posthog.temporal.alerts.schedule.a_update_schedule",
            new=AsyncMock(),
        ) as mock_update,
    ):
        await create_schedule_due_alert_checks_schedule(mock_client)

    mock_update.assert_awaited_once()
    mock_create.assert_not_awaited()
