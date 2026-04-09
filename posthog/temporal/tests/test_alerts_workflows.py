import datetime as dt

import pytest
from unittest.mock import AsyncMock, patch

from temporalio.client import Schedule, ScheduleActionStartWorkflow, ScheduleOverlapPolicy, ScheduleSpec

from posthog.temporal.alerts.schedule import create_schedule_all_alert_checks_schedule
from posthog.temporal.alerts.workflows import CheckAlertWorkflow, ScheduleAllAlertChecksWorkflow


def test_schedule_all_alert_checks_workflow_parses_empty_inputs():
    inputs = ScheduleAllAlertChecksWorkflow.parse_inputs([])
    assert inputs is not None


def test_schedule_all_alert_checks_workflow_parses_json_inputs():
    inputs = ScheduleAllAlertChecksWorkflow.parse_inputs(["{}"])
    assert inputs is not None


def test_check_alert_workflow_parses_inputs_with_slo():
    payload = (
        '{"alert_id":"abc","team_id":1,"distinct_id":"abc","calculation_interval":"hourly","insight_id":42,"slo":null}'
    )
    inputs = CheckAlertWorkflow.parse_inputs([payload])
    assert inputs.alert_id == "abc"
    assert inputs.team_id == 1
    assert inputs.slo is None


# Behavioral tests — implemented in PR2 once the activities have real bodies.
# These names are placeholders so the test file documents the intended coverage.


@pytest.mark.skip(reason="Implementation in PR2 — requires evaluate/notify activity bodies")
def test_schedule_all_alert_checks_dispatches_due_alerts():
    pass


@pytest.mark.skip(reason="Implementation in PR2")
def test_schedule_all_alert_checks_swallows_already_started():
    pass


@pytest.mark.skip(reason="Implementation in PR2")
def test_schedule_all_alert_checks_raises_on_other_failures():
    pass


@pytest.mark.skip(reason="Implementation in PR2")
def test_check_alert_workflow_skip_path_exits_cleanly():
    pass


@pytest.mark.skip(reason="Implementation in PR2")
def test_check_alert_workflow_auto_disable_path_exits_cleanly():
    pass


@pytest.mark.skip(reason="Implementation in PR2")
def test_check_alert_workflow_evaluate_then_notify_happy_path():
    pass


@pytest.mark.skip(reason="Implementation in PR2")
def test_check_alert_workflow_evaluate_success_no_notify():
    pass


@pytest.mark.skip(reason="Implementation in PR2")
def test_check_alert_workflow_evaluate_failure_re_raises():
    pass


@pytest.mark.skip(reason="Implementation in PR2")
def test_check_alert_workflow_notify_failure_does_not_re_run_evaluate():
    pass


@pytest.mark.skip(reason="Implementation in PR2")
def test_check_alert_workflow_emits_slo_completion_properties():
    pass


@pytest.mark.skip(reason="Implementation in PR2 — regression test for orphaned starts")
def test_check_alert_workflow_replay_does_not_double_emit_slo():
    pass


@pytest.mark.asyncio
async def test_create_schedule_all_alert_checks_schedule_creates_when_absent():
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
        await create_schedule_all_alert_checks_schedule(mock_client)

    mock_create.assert_awaited_once()
    mock_update.assert_not_awaited()

    # Inspect the schedule passed to a_create_schedule
    call_args = mock_create.await_args
    assert call_args is not None
    schedule_arg = call_args.args[2]
    assert isinstance(schedule_arg, Schedule)
    assert isinstance(schedule_arg.spec, ScheduleSpec)
    assert schedule_arg.spec.cron_expressions == ["*/2 * * * *"]
    assert schedule_arg.policy.overlap == ScheduleOverlapPolicy.ALLOW_ALL
    # Narrow from the ScheduleAction base to read execution_timeout.
    assert isinstance(schedule_arg.action, ScheduleActionStartWorkflow)
    assert schedule_arg.action.execution_timeout == dt.timedelta(minutes=10)
    # trigger_immediately should default to False (kwargs check)
    assert call_args.kwargs.get("trigger_immediately") is False


@pytest.mark.asyncio
async def test_create_schedule_all_alert_checks_schedule_updates_when_present():
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
        await create_schedule_all_alert_checks_schedule(mock_client)

    mock_update.assert_awaited_once()
    mock_create.assert_not_awaited()
