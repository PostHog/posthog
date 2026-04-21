import uuid
import datetime as dt
from concurrent.futures import ThreadPoolExecutor

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from django.conf import settings

import pytest_asyncio
from asgiref.sync import sync_to_async
from temporalio.client import Client, Schedule, ScheduleActionStartWorkflow, ScheduleOverlapPolicy, ScheduleSpec
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


# ─── CheckAlertWorkflow integration tests ────────────────────────────
#
# Exercise the full prepare → evaluate → notify chain against a real Postgres
# DB with mocked ClickHouse + SMTP. Catches wiring regressions between the
# workflow and activities — e.g., missing fields on activity inputs.


CHECK_ALERT_ACTIVITIES = [prepare_alert, evaluate_alert, notify_alert]


def _valid_trends_query() -> dict:
    return TrendsQuery(
        series=[EventsNode(event="$pageview")],
        interval=IntervalType.DAY,
        trendsFilter=TrendsFilter(display=ChartDisplayType.BOLD_NUMBER),
    ).model_dump()


@sync_to_async
def _create_alert(ateam, *, insight_deleted: bool = False, enabled: bool = True) -> AlertConfiguration:
    insight = Insight.objects.create(team=ateam, name="insight", query=_valid_trends_query(), deleted=insight_deleted)
    return AlertConfiguration.objects.create(
        team=ateam,
        insight=insight,
        name="wf-test-alert",
        enabled=enabled,
        calculation_interval=AlertCalculationInterval.DAILY.value,
        config={"type": "TrendsAlertConfig", "series_index": 0},
        condition={"type": "absolute_value"},
    )


@pytest_asyncio.fixture
async def alert_with_subscriber(ateam, aorganization):
    @sync_to_async
    def _create() -> AlertConfiguration:
        user = User.objects.create_and_join(
            organization=aorganization,
            email=f"alerts-wf-{uuid.uuid4().hex[:6]}@posthog.com",
            password=None,
        )
        alert = AlertConfiguration.objects.create(
            team=ateam,
            insight=Insight.objects.create(team=ateam, name="insight", query=_valid_trends_query()),
            name="wf-test-alert",
            enabled=True,
            calculation_interval=AlertCalculationInterval.DAILY.value,
            config={"type": "TrendsAlertConfig", "series_index": 0},
            condition={"type": "absolute_value"},
        )
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
            activity_executor=ThreadPoolExecutor(max_workers=2),
            debug_mode=True,
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
    temporal_client: Client,
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

    # Contract: workflow pipes breaches from evaluate into notify inputs, and the
    # idempotency_key is the AlertCheck id (so MessagingRecord dedupes retries).
    mock_send_breaches.assert_called_once()
    _, pos_args, kw_args = mock_send_breaches.mock_calls[0]
    passed_breaches = pos_args[1] if len(pos_args) > 1 else kw_args.get("breaches")
    assert passed_breaches == ["value above threshold"]
    assert kw_args.get("idempotency_key") == str(check.id)

    started_calls = [
        c for c in mock_slo_analytics.capture.call_args_list if c.kwargs.get("event") == "slo_operation_started"
    ]
    assert len(started_calls) == 1
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
            SkipReason.NOT_FOUND,
            id="disabled_treated_as_not_found",
        ),
    ],
)
@patch("posthog.slo.events.posthoganalytics")
@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_check_alert_workflow_skip_short_circuits_before_evaluate(
    mock_slo_analytics: MagicMock,
    temporal_client: Client,
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
    temporal_client: Client,
    alert_with_subscriber: AlertConfiguration,
) -> None:
    # Permanent evaluation errors are captured into AlertCheck.error (not re-raised),
    # so the workflow completes normally with state=ERRORED and the notify activity
    # fires error notifications. This exercises the "error" path end-to-end.
    class PermanentError(Exception):
        pass

    with (
        patch(
            "posthog.temporal.alerts.activities.check_alert_for_insight",
            side_effect=PermanentError("insight query broken"),
        ),
        patch("posthog.tasks.alerts.utils.send_notifications_for_errors") as mock_send_errors,
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

    mock_send_errors.assert_called_once()

    # Error captured → alert degraded (state=ERRORED), not a workflow failure → SLO=SUCCESS.
    completed_props = _completed_slo_props(mock_slo_analytics)
    assert completed_props["outcome"] == SloOutcome.SUCCESS
    assert completed_props["alert_state"] == AlertState.ERRORED
