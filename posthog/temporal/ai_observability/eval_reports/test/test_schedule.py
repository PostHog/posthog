from datetime import timedelta

import pytest
from unittest import mock

from temporalio.client import ScheduleActionStartWorkflow, ScheduleOverlapPolicy

from posthog.temporal.ai_observability.eval_reports.schedule import (
    create_count_trigger_schedule,
    create_eval_reports_schedule,
)
from posthog.temporal.ai_observability.eval_reports.types import (
    DEFAULT_MAX_COUNT_TRIGGERED_EVAL_REPORTS_PER_RUN,
    DEFAULT_MAX_SCHEDULED_EVAL_REPORTS_PER_RUN,
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "create_schedule, expected_maximum, expected_catchup_window",
    [
        (create_eval_reports_schedule, DEFAULT_MAX_SCHEDULED_EVAL_REPORTS_PER_RUN, timedelta(hours=1)),
        (create_count_trigger_schedule, DEFAULT_MAX_COUNT_TRIGGERED_EVAL_REPORTS_PER_RUN, timedelta(minutes=5)),
    ],
)
async def test_eval_report_schedules_have_bounded_inputs_and_explicit_recovery_policy(
    create_schedule, expected_maximum: int, expected_catchup_window: timedelta
) -> None:
    captured = []
    with (
        mock.patch("posthog.temporal.ai_observability.eval_reports.schedule.settings.CLOUD_DEPLOYMENT", "EU"),
        mock.patch(
            "posthog.temporal.ai_observability.eval_reports.schedule.a_schedule_exists",
            new=mock.AsyncMock(return_value=False),
        ),
        mock.patch(
            "posthog.temporal.ai_observability.eval_reports.schedule.a_create_schedule",
            new=mock.AsyncMock(side_effect=lambda client, schedule_id, schedule, **kwargs: captured.append(schedule)),
        ),
    ):
        await create_schedule(mock.MagicMock())

    schedule = captured[0]
    assert isinstance(schedule.action, ScheduleActionStartWorkflow)
    assert schedule.action.args == [
        {
            "max_reports_per_run": expected_maximum,
            "region": "eu",
            **({"buffer_minutes": 15} if expected_catchup_window == timedelta(hours=1) else {}),
        }
    ]
    assert schedule.action.execution_timeout == timedelta(minutes=10)
    assert schedule.action.retry_policy is not None
    assert schedule.action.retry_policy.maximum_attempts == 1
    assert schedule.policy.overlap == ScheduleOverlapPolicy.SKIP
    assert schedule.policy.catchup_window == expected_catchup_window
    assert schedule.policy.pause_on_failure is False
