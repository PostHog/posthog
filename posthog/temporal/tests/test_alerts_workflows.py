import uuid
from collections.abc import Callable
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from django.conf import settings

import pytest_asyncio
from asgiref.sync import sync_to_async
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.schema import (
    AlertCalculationInterval,
    AlertState,
    ChartDisplayType,
    EventsNode,
    IntervalType,
    TrendsFilter,
    TrendsQuery,
)

from posthog.models import AlertConfiguration, Insight, User
from posthog.models.alert import AlertCheck
from posthog.slo.types import SloArea, SloConfig, SloOperation, SloOutcome
from posthog.tasks.alerts.utils import AlertEvaluationResult
from posthog.temporal.alerts.activities import evaluate_alert, notify_alert, prepare_alert
from posthog.temporal.alerts.schedule import create_schedule_due_alert_checks_schedule
from posthog.temporal.alerts.types import CheckAlertWorkflowInputs, SkipReason
from posthog.temporal.alerts.workflows import CheckAlertWorkflow
from posthog.temporal.common.slo_interceptor import SloInterceptor

CHECK_ALERT_ACTIVITIES: list[Callable[..., Any]] = [prepare_alert, evaluate_alert, notify_alert]


def test_schedule_is_registered_in_init_schedules():
    from posthog.temporal.schedule import schedules

    assert create_schedule_due_alert_checks_schedule in schedules


def _valid_trends_query() -> dict:
    return TrendsQuery(
        series=[EventsNode(event="$pageview")],
        interval=IntervalType.DAY,
        trendsFilter=TrendsFilter(display=ChartDisplayType.BOLD_NUMBER),
    ).model_dump()


def _build_alert(
    ateam,
    *,
    insight_deleted: bool = False,
    enabled: bool = True,
    config: dict | None = None,
) -> AlertConfiguration:
    insight = Insight.objects.create(team=ateam, name="insight", query=_valid_trends_query(), deleted=insight_deleted)
    return AlertConfiguration.objects.create(
        team=ateam,
        insight=insight,
        name="wf-test-alert",
        enabled=enabled,
        calculation_interval=AlertCalculationInterval.DAILY.value,
        config=config if config is not None else {"type": "TrendsAlertConfig", "series_index": 0},
        condition={"type": "absolute_value"},
    )


@sync_to_async
def _create_alert(
    ateam,
    *,
    insight_deleted: bool = False,
    enabled: bool = True,
    config: dict | None = None,
) -> AlertConfiguration:
    return _build_alert(ateam, insight_deleted=insight_deleted, enabled=enabled, config=config)


@pytest_asyncio.fixture
async def alert_with_subscriber(ateam, aorganization):
    @sync_to_async
    def _create() -> AlertConfiguration:
        user = User.objects.create_and_join(
            organization=aorganization,
            email=f"alerts-wf-{uuid.uuid4().hex[:6]}@posthog.com",
            password=None,
        )
        alert = _build_alert(ateam)
        alert.subscribed_users.add(user)
        return alert

    return await _create()


def _slo_config(alert: AlertConfiguration) -> SloConfig:
    return SloConfig(
        operation=SloOperation.ALERT_CHECK,
        area=SloArea.ANALYTIC_PLATFORM,
        team_id=alert.team_id,
        resource_id=str(alert.id),
        distinct_id=str(alert.id),
        start_properties={"calculation_interval": alert.calculation_interval, "insight_id": alert.insight_id},
        completion_properties={
            "calculation_interval": alert.calculation_interval,
            "insight_id": alert.insight_id,
        },
    )


async def _run_check_alert_workflow(alert_id: str, slo: SloConfig, team_id: int, insight_id: int) -> None:
    """Spin up a WorkflowEnvironment + Worker and execute CheckAlertWorkflow.

    Caller patches the boundaries (check_alert_for_insight, send_notifications_for_breaches)
    before invoking. The workflow runs to completion (including its `finally` SLO cleanup).
    """
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=settings.TEMPORAL_TASK_QUEUE,
            workflows=[CheckAlertWorkflow],
            activities=CHECK_ALERT_ACTIVITIES,
            interceptors=[SloInterceptor()],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            await env.client.execute_workflow(
                CheckAlertWorkflow.run,
                CheckAlertWorkflowInputs(
                    alert_id=alert_id,
                    team_id=team_id,
                    distinct_id=alert_id,
                    calculation_interval=AlertCalculationInterval.DAILY.value,
                    insight_id=insight_id,
                    slo=slo,
                ),
                id=f"check-alert-{uuid.uuid4()}",
                task_queue=settings.TEMPORAL_TASK_QUEUE,
            )


def _completed_slo_props(mock_slo_analytics: MagicMock) -> dict:
    completed = [
        c for c in mock_slo_analytics.capture.call_args_list if c.kwargs.get("event") == "slo_operation_completed"
    ]
    assert len(completed) == 1, f"expected 1 SLO completion event, got {len(completed)}"
    return completed[0].kwargs["properties"]


@patch("posthog.slo.events.posthoganalytics")
@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_check_alert_workflow_firing_drives_full_chain_with_slo(
    mock_slo_analytics: MagicMock,
    alert_with_subscriber: AlertConfiguration,
) -> None:
    evaluation_result = AlertEvaluationResult(value=100.0, breaches=["value above threshold"])
    recipients = ["alerts-wf-test@posthog.com"]

    with (
        patch("posthog.temporal.alerts.activities.check_alert_for_insight", return_value=evaluation_result),
        patch(
            "posthog.tasks.alerts.utils.send_notifications_for_breaches", return_value=recipients
        ) as mock_send_breaches,
    ):
        await _run_check_alert_workflow(
            alert_id=str(alert_with_subscriber.id),
            slo=_slo_config(alert_with_subscriber),
            team_id=alert_with_subscriber.team_id,
            insight_id=alert_with_subscriber.insight_id,
        )

    checks = await sync_to_async(lambda: list(AlertCheck.objects.filter(alert_configuration=alert_with_subscriber)))()
    assert len(checks) == 1
    check = checks[0]
    assert check.state == AlertState.FIRING
    assert check.targets_notified == {"users": recipients}

    mock_send_breaches.assert_called_once()
    call = mock_send_breaches.call_args
    assert call.args[1] == ["value above threshold"]
    assert call.kwargs.get("idempotency_key") == str(check.id)

    completed_props = _completed_slo_props(mock_slo_analytics)
    assert completed_props["outcome"] == SloOutcome.SUCCESS
    assert completed_props["alert_state"] == AlertState.FIRING
    assert completed_props["calculation_interval"] == alert_with_subscriber.calculation_interval


@pytest.mark.parametrize(
    "setup,expected_reason",
    [
        pytest.param(
            lambda ateam: _create_alert(ateam, insight_deleted=True),
            SkipReason.INSIGHT_DELETED,
            id="insight_deleted",
        ),
        pytest.param(
            lambda ateam: _create_alert(ateam, enabled=False),
            SkipReason.DISABLED,
            id="disabled",
        ),
    ],
)
@patch("posthog.slo.events.posthoganalytics")
@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_check_alert_workflow_skip_short_circuits_before_evaluate(
    mock_slo_analytics: MagicMock,
    ateam,
    setup,
    expected_reason: SkipReason,
) -> None:
    alert = await setup(ateam)

    with (
        patch("posthog.temporal.alerts.activities.check_alert_for_insight") as mock_ch_query,
        patch("posthog.tasks.alerts.utils.send_notifications_for_breaches") as mock_send_breaches,
    ):
        await _run_check_alert_workflow(
            alert_id=str(alert.id),
            slo=_slo_config(alert),
            team_id=alert.team_id,
            insight_id=alert.insight_id,
        )

    check_count = await sync_to_async(AlertCheck.objects.filter(alert_configuration=alert).count)()
    assert check_count == 0
    mock_ch_query.assert_not_called()
    mock_send_breaches.assert_not_called()

    completed_props = _completed_slo_props(mock_slo_analytics)
    assert completed_props["outcome"] == SloOutcome.SUCCESS
    assert completed_props.get("skip_reason") == expected_reason
    assert "alert_state" not in completed_props


@patch("posthog.slo.events.posthoganalytics")
@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_check_alert_workflow_records_errored_check_on_permanent_evaluation_failure(
    mock_slo_analytics: MagicMock,
    alert_with_subscriber: AlertConfiguration,
) -> None:
    class PermanentError(Exception):
        pass

    with (
        patch(
            "posthog.temporal.alerts.activities.check_alert_for_insight",
            side_effect=PermanentError("insight query broken"),
        ),
        patch(
            "posthog.tasks.alerts.utils.send_notifications_for_errors",
            return_value=["alerts-wf-test@posthog.com"],
        ) as mock_send_errors,
    ):
        await _run_check_alert_workflow(
            alert_id=str(alert_with_subscriber.id),
            slo=_slo_config(alert_with_subscriber),
            team_id=alert_with_subscriber.team_id,
            insight_id=alert_with_subscriber.insight_id,
        )

    check = await sync_to_async(
        lambda: AlertCheck.objects.filter(alert_configuration=alert_with_subscriber).order_by("-created_at").first()
    )()
    assert check is not None
    assert check.state == AlertState.ERRORED
    assert check.error is not None
    assert "insight query broken" in check.error["message"]

    # Evaluate-time errors are transient — alert stays enabled so next run retries.
    # Only prepare-time validate_alert_config failures call disable_invalid_alert.
    refreshed = await sync_to_async(AlertConfiguration.objects.get)(pk=alert_with_subscriber.pk)
    assert refreshed.enabled is True

    mock_send_errors.assert_called_once()

    completed_props = _completed_slo_props(mock_slo_analytics)
    # Errored evaluation = degraded alert, not a workflow failure → SLO stays SUCCESS.
    assert completed_props["outcome"] == SloOutcome.SUCCESS
    assert completed_props["alert_state"] == AlertState.ERRORED


@patch("posthog.slo.events.posthoganalytics")
@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_check_alert_workflow_auto_disables_alert_with_invalid_config(
    mock_slo_analytics: MagicMock,
    ateam,
) -> None:
    # Missing required "type" in config → validate_alert_config raises ValueError at prepare
    # → disable_invalid_alert flips enabled=False and writes an ERRORED AlertCheck row.
    alert = await _create_alert(ateam, config={"series_index": 0})

    with (
        patch("posthog.temporal.alerts.activities.check_alert_for_insight") as mock_ch_query,
        patch("posthog.tasks.alerts.utils.send_notifications_for_breaches") as mock_send_breaches,
    ):
        await _run_check_alert_workflow(
            alert_id=str(alert.id),
            slo=_slo_config(alert),
            team_id=alert.team_id,
            insight_id=alert.insight_id,
        )

    refreshed = await sync_to_async(AlertConfiguration.objects.get)(pk=alert.pk)
    assert refreshed.enabled is False
    assert refreshed.state == AlertState.ERRORED

    check = await sync_to_async(AlertCheck.objects.get)(alert_configuration=refreshed)
    assert check.state == AlertState.ERRORED
    assert check.calculated_value is None
    assert check.error is not None

    # Disable short-circuits before evaluate / notify.
    mock_ch_query.assert_not_called()
    mock_send_breaches.assert_not_called()

    completed_props = _completed_slo_props(mock_slo_analytics)
    assert completed_props["outcome"] == SloOutcome.SUCCESS
    assert completed_props.get("skip_reason") is not None
    assert "alert_state" not in completed_props
