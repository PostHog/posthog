from datetime import timedelta

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from temporalio.client import ScheduleOverlapPolicy

from posthog.temporal.ai_observability.eval_reports.schedule import (
    create_count_trigger_schedule,
    create_eval_reports_schedule,
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "create_schedule,expected_args,expected_timeout,expected_catchup",
    [
        (
            create_eval_reports_schedule,
            {"buffer_minutes": 15, "max_reports_per_run": 300},
            timedelta(minutes=10),
            timedelta(hours=1),
        ),
        (
            create_count_trigger_schedule,
            {"max_reports_per_run": 800},
            timedelta(minutes=30),
            timedelta(minutes=5),
        ),
    ],
)
async def test_eval_report_schedules_have_bounded_inputs_and_explicit_policy(
    create_schedule,
    expected_args: dict,
    expected_timeout: timedelta,
    expected_catchup: timedelta,
) -> None:
    create = AsyncMock()

    with (
        patch(
            "posthog.temporal.ai_observability.eval_reports.schedule.a_schedule_exists",
            new=AsyncMock(return_value=False),
        ),
        patch("posthog.temporal.ai_observability.eval_reports.schedule.a_create_schedule", new=create),
    ):
        await create_schedule(MagicMock())

    schedule = create.await_args.args[2]
    assert schedule.action.args == [expected_args]
    assert schedule.action.execution_timeout == expected_timeout
    assert schedule.policy.overlap is ScheduleOverlapPolicy.SKIP
    assert schedule.policy.catchup_window == expected_catchup
