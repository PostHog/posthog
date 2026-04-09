import datetime as dt

import pytest

from temporalio.common import RetryPolicy
from temporalio.testing import ActivityEnvironment

from posthog.slo.types import SloArea, SloConfig, SloOperation
from posthog.temporal.alerts.activities import (
    enumerate_due_alerts_activity,
    evaluate_alert_activity,
    notify_alert_activity,
    prepare_alert_activity,
)
from posthog.temporal.alerts.retry_policy import ALERT_EVALUATE_RETRY_POLICY, ALERT_NOTIFY_RETRY_POLICY
from posthog.temporal.alerts.types import (
    AlertInfo,
    CheckAlertWorkflowInputs,
    EnumerateDueAlertsActivityInputs,
    EvaluateAlertActivityInputs,
    EvaluateAlertResult,
    NotifyAlertActivityInputs,
    PrepareAlertActivityInputs,
    PrepareAlertResult,
    ScheduleAllAlertChecksWorkflowInputs,
)


def test_alert_info_can_be_instantiated():
    info = AlertInfo(
        alert_id="abc",
        team_id=1,
        distinct_id="abc",
        calculation_interval="hourly",
        insight_id=42,
    )
    assert info.alert_id == "abc"
    assert info.team_id == 1
    assert info.calculation_interval == "hourly"


def test_check_alert_workflow_inputs_with_slo():
    inputs = CheckAlertWorkflowInputs(
        alert_id="abc",
        team_id=1,
        distinct_id="abc",
        calculation_interval="hourly",
        insight_id=42,
        slo=SloConfig(
            operation=SloOperation.ALERT_CHECK,
            area=SloArea.ANALYTIC_PLATFORM,
            team_id=1,
            resource_id="abc",
            distinct_id="abc",
        ),
    )
    assert inputs.slo is not None
    assert inputs.slo.operation == SloOperation.ALERT_CHECK


def test_check_alert_workflow_inputs_without_slo_defaults_to_none():
    inputs = CheckAlertWorkflowInputs(
        alert_id="abc",
        team_id=1,
        distinct_id="abc",
        calculation_interval=None,
        insight_id=42,
    )
    assert inputs.slo is None


def test_prepare_alert_result_actions():
    assert PrepareAlertResult(action="evaluate").reason is None
    assert PrepareAlertResult(action="skip", reason="snoozed").reason == "snoozed"
    assert PrepareAlertResult(action="auto_disable", reason="invalid").reason == "invalid"


def test_evaluate_alert_result():
    result = EvaluateAlertResult(
        alert_check_id=123,
        should_notify=True,
        new_state="firing",
    )
    assert result.alert_check_id == 123
    assert result.should_notify is True
    assert result.new_state == "firing"


def test_activity_input_types_construct():
    EnumerateDueAlertsActivityInputs()
    PrepareAlertActivityInputs(alert_id="abc")
    EvaluateAlertActivityInputs(alert_id="abc")
    NotifyAlertActivityInputs(alert_id="abc", alert_check_id=123)


def test_schedule_all_alert_checks_workflow_inputs_construct():
    ScheduleAllAlertChecksWorkflowInputs()


def test_alert_evaluate_retry_policy_is_valid():
    assert isinstance(ALERT_EVALUATE_RETRY_POLICY, RetryPolicy)
    assert ALERT_EVALUATE_RETRY_POLICY.maximum_attempts == 4
    assert ALERT_EVALUATE_RETRY_POLICY.initial_interval == dt.timedelta(seconds=1)
    assert ALERT_EVALUATE_RETRY_POLICY.maximum_interval == dt.timedelta(seconds=10)
    assert ALERT_EVALUATE_RETRY_POLICY.backoff_coefficient == 2.0


def test_alert_notify_retry_policy_is_valid():
    assert isinstance(ALERT_NOTIFY_RETRY_POLICY, RetryPolicy)
    assert ALERT_NOTIFY_RETRY_POLICY.maximum_attempts == 5
    assert ALERT_NOTIFY_RETRY_POLICY.initial_interval == dt.timedelta(seconds=5)
    assert ALERT_NOTIFY_RETRY_POLICY.maximum_interval == dt.timedelta(minutes=2)
    assert ALERT_NOTIFY_RETRY_POLICY.backoff_coefficient == 2.0


def test_activities_have_temporalio_activity_definition():
    # Each Temporal activity has a __temporal_activity_definition attribute
    # set by the @temporalio.activity.defn decorator. If any of these is
    # missing, the activity won't be registerable on a worker.
    for activity_fn in (
        enumerate_due_alerts_activity,
        prepare_alert_activity,
        evaluate_alert_activity,
        notify_alert_activity,
    ):
        assert hasattr(activity_fn, "__temporal_activity_definition"), (
            f"{activity_fn.__name__} is missing the @temporalio.activity.defn decorator"
        )


@pytest.mark.asyncio
async def test_prepare_alert_activity_stub_raises_not_implemented():
    env = ActivityEnvironment()
    with pytest.raises(NotImplementedError, match="follow-up PR"):
        await env.run(prepare_alert_activity, PrepareAlertActivityInputs(alert_id="abc"))


@pytest.mark.asyncio
async def test_evaluate_alert_activity_stub_raises_not_implemented():
    env = ActivityEnvironment()
    with pytest.raises(NotImplementedError, match="follow-up PR"):
        await env.run(evaluate_alert_activity, EvaluateAlertActivityInputs(alert_id="abc"))


@pytest.mark.asyncio
async def test_notify_alert_activity_stub_raises_not_implemented():
    env = ActivityEnvironment()
    with pytest.raises(NotImplementedError, match="follow-up PR"):
        await env.run(notify_alert_activity, NotifyAlertActivityInputs(alert_id="abc", alert_check_id=1))
