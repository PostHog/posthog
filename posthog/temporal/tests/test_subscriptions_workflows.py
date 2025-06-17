"""Temporal subscription workflow tests."""

import uuid
from unittest.mock import MagicMock, patch

import pytest
from freezegun import freeze_time
from temporalio.client import Client
from temporalio.common import RetryPolicy
from temporalio.worker import Worker, UnsandboxedWorkflowRunner

from ee.tasks.test.subscriptions.subscriptions_test_factory import create_subscription
from posthog.models.dashboard import Dashboard
from posthog.models.dashboard_tile import DashboardTile
from posthog.models.insight import Insight
from posthog.models.exported_asset import ExportedAsset
from posthog.models.instance_setting import set_instance_setting
from posthog.temporal.subscriptions.subscription_scheduling_workflow import (
    ScheduleAllSubscriptionsWorkflow,
    HandleSubscriptionValueChangeWorkflow,
    deliver_subscription_report_activity,
    fetch_due_subscriptions_activity,
    DeliverSubscriptionReportActivityInputs,
)

TASK_QUEUE = "TEST-SUBSCRIPTIONS-TQ"


@pytest.fixture
async def subscriptions_worker(temporal_client: Client):
    async with Worker(
        temporal_client,
        task_queue=TASK_QUEUE,
        workflows=[ScheduleAllSubscriptionsWorkflow, HandleSubscriptionValueChangeWorkflow],
        activities=[deliver_subscription_report_activity, fetch_due_subscriptions_activity],
        workflow_runner=UnsandboxedWorkflowRunner(),
    ):
        yield


@pytest.mark.asyncio
@patch("ee.tasks.subscriptions.send_email_subscription_report")
@patch("ee.tasks.subscriptions.generate_assets")
@freeze_time("2022-02-02T08:55:00.000Z")
async def test_schedule_all_subscriptions_workflow(
    mock_gen_assets: MagicMock,
    mock_send_email: MagicMock,
    temporal_client: Client,
    subscriptions_worker,
    team,
    user,
):
    dashboard = Dashboard.objects.create(team=team, name="dash", created_by=user)
    insight = Insight.objects.create(team=team, short_id="123456", name="insight")

    for i in range(5):
        DashboardTile.objects.create(
            dashboard=dashboard,
            insight=Insight.objects.create(team=team, short_id=f"{i}", name=f"i{i}"),
        )

    set_instance_setting("EMAIL_HOST", "x")
    set_instance_setting("EMAIL_ENABLED", True)

    with freeze_time("2022-02-02T08:30:00.000Z"):
        create_subscription(team=team, insight=insight, created_by=user)
        create_subscription(team=team, insight=insight, created_by=user)

    handle = await temporal_client.start_workflow(
        ScheduleAllSubscriptionsWorkflow.run,
        ScheduleAllSubscriptionsWorkflow.inputs_cls()(buffer_minutes=15),
        id=str(uuid.uuid4()),
        task_queue=TASK_QUEUE,
        retry_policy=RetryPolicy(maximum_attempts=1),
    )
    await handle.result()

    assert mock_send_email.call_count == 4  # two recipients per subscription


@pytest.mark.asyncio
@patch("ee.tasks.subscriptions.send_email_subscription_report")
@patch("ee.tasks.subscriptions.generate_assets")
async def test_handle_subscription_value_change_workflow(
    mock_gen_assets: MagicMock,
    mock_send_email: MagicMock,
    temporal_client: Client,
    subscriptions_worker,
    team,
    user,
):
    insight = Insight.objects.create(team=team, short_id="123", name="insight")
    subscription = create_subscription(
        team=team,
        insight=insight,
        created_by=user,
        target_value="a@b.com,c@d.com",
    )
    asset = ExportedAsset.objects.create(team=team, insight_id=insight.id, export_format="image/png")
    mock_gen_assets.return_value = [insight], [asset]

    handle = await temporal_client.start_workflow(
        HandleSubscriptionValueChangeWorkflow.run,
        DeliverSubscriptionReportActivityInputs(
            subscription_id=subscription.id,
            previous_value="a@b.com",
            invite_message=None,
        ),
        id=str(uuid.uuid4()),
        task_queue=TASK_QUEUE,
    )
    await handle.result()

    mock_send_email.assert_called_once()
    assert mock_send_email.call_args[0][0] == "c@d.com"
