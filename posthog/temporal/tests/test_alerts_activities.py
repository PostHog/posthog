import pytest

from temporalio.common import RetryPolicy
from temporalio.testing import ActivityEnvironment

from posthog.temporal.alerts.activities import evaluate_alert_activity, notify_alert_activity, prepare_alert_activity
from posthog.temporal.alerts.retry_policy import ALERT_EVALUATE_RETRY_POLICY, ALERT_NOTIFY_RETRY_POLICY
from posthog.temporal.alerts.types import (
    EvaluateAlertActivityInputs,
    NotifyAlertActivityInputs,
    PrepareAlertActivityInputs,
)


def test_retry_policies_are_retry_policy_instances():
    # Smoke check — the concrete values live in retry_policy.py and aren't
    # worth mirroring in a test (mechanical re-statement catches nothing).
    assert isinstance(ALERT_EVALUATE_RETRY_POLICY, RetryPolicy)
    assert isinstance(ALERT_NOTIFY_RETRY_POLICY, RetryPolicy)


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


def test_alerts_module_exports_workflows_and_activities():
    from posthog.temporal.alerts import ACTIVITIES, WORKFLOWS
    from posthog.temporal.alerts.activities import (
        enumerate_due_alerts_activity,
        evaluate_alert_activity,
        notify_alert_activity,
        prepare_alert_activity,
    )
    from posthog.temporal.alerts.workflows import CheckAlertWorkflow, ScheduleAllAlertChecksWorkflow

    assert ScheduleAllAlertChecksWorkflow in WORKFLOWS
    assert CheckAlertWorkflow in WORKFLOWS
    assert len(WORKFLOWS) == 2

    assert enumerate_due_alerts_activity in ACTIVITIES
    assert prepare_alert_activity in ACTIVITIES
    assert evaluate_alert_activity in ACTIVITIES
    assert notify_alert_activity in ACTIVITIES
    assert len(ACTIVITIES) == 4


def test_alerts_workflows_registered_on_analytics_platform_worker():
    from django.conf import settings

    from posthog.management.commands.start_temporal_worker import ACTIVITIES_DICT, WORKFLOWS_DICT
    from posthog.temporal.alerts import (
        ACTIVITIES as ALERT_ACTIVITIES,
        WORKFLOWS as ALERT_WORKFLOWS,
    )

    queue_workflows = WORKFLOWS_DICT[settings.ANALYTICS_PLATFORM_TASK_QUEUE]
    queue_activities = ACTIVITIES_DICT[settings.ANALYTICS_PLATFORM_TASK_QUEUE]

    for workflow_cls in ALERT_WORKFLOWS:
        assert workflow_cls in queue_workflows, (
            f"{workflow_cls.__name__} not registered on ANALYTICS_PLATFORM_TASK_QUEUE"
        )

    for activity_fn in ALERT_ACTIVITIES:
        assert activity_fn in queue_activities, (
            f"{activity_fn.__name__} not registered on ANALYTICS_PLATFORM_TASK_QUEUE"
        )
