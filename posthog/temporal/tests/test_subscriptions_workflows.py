from __future__ import annotations

import pytest

import uuid
from datetime import datetime
from zoneinfo import ZoneInfo
from unittest.mock import MagicMock, patch

from freezegun import freeze_time
from asgiref.sync import sync_to_async
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

pytestmark = [pytest.mark.django_db]


@pytest.fixture
async def subscriptions_worker(temporal_client: Client):
    """Spin up a Temporal worker for subscription workflows/activities."""

    async with Worker(
        temporal_client,
        task_queue=TASK_QUEUE,
        workflows=[ScheduleAllSubscriptionsWorkflow, HandleSubscriptionValueChangeWorkflow],
        activities=[deliver_subscription_report_activity, fetch_due_subscriptions_activity],
        workflow_runner=UnsandboxedWorkflowRunner(),
    ):
        yield  # allow the test to run while the worker is active


@pytest.mark.asyncio
@freeze_time("2022-02-02T08:55:00.000Z")
@patch("ee.tasks.subscriptions.send_email_subscription_report")
@patch("ee.tasks.subscriptions.generate_assets")
async def test_schedule_all_subscriptions_workflow(
    mock_generate_assets: MagicMock,
    mock_send_email: MagicMock,
    temporal_client: Client,
    subscriptions_worker,
    team,
    user,
):
    """Workflow should deliver reports only for subscriptions due within buffer."""

    # Basic dashboard/insight setup
    dashboard = await sync_to_async(Dashboard.objects.create)(team=team, name="Dashboard", created_by=user)
    insight = await sync_to_async(Insight.objects.create)(team=team, short_id="abc123", name="Base insight")

    # Create extra tiles to simulate heavy dashboards
    for idx in range(3):
        await sync_to_async(DashboardTile.objects.create)(
            dashboard=dashboard,
            insight=await sync_to_async(Insight.objects.create)(team=team, short_id=f"tile{idx}", name=f"tile {idx}"),
        )

    # Pretend asset generator returns 1 asset
    asset = await sync_to_async(ExportedAsset.objects.create)(
        team=team, insight_id=insight.id, export_format="image/png"
    )
    mock_generate_assets.return_value = [insight], [asset]

    await sync_to_async(set_instance_setting)("EMAIL_HOST", "fake")
    await sync_to_async(set_instance_setting)("EMAIL_ENABLED", True)

    with freeze_time("2022-02-02T08:30:00.000Z"):
        subs_due = [
            await sync_to_async(create_subscription)(team=team, insight=insight, created_by=user),
            await sync_to_async(create_subscription)(team=team, insight=insight, created_by=user),
        ]
        # Not-due subscription scheduled 1h later
        future_sub = await sync_to_async(create_subscription)(team=team, dashboard=dashboard, created_by=user)

    # Push future_sub next delivery to 10:00 UTC so it's outside 15-min buffer
    future_sub.start_date = datetime(2022, 1, 1, 10, 0, tzinfo=ZoneInfo("UTC"))
    await sync_to_async(future_sub.save)()

    # Run workflow
    wf_handle = await temporal_client.start_workflow(
        ScheduleAllSubscriptionsWorkflow.run,
        # buffer 15 minutes
        ScheduleAllSubscriptionsWorkflow.inputs_cls()(buffer_minutes=15)
        if hasattr(ScheduleAllSubscriptionsWorkflow, "inputs_cls")
        else ScheduleAllSubscriptionsWorkflow.__annotations__["inputs"](buffer_minutes=15),
        id=str(uuid.uuid4()),
        task_queue=TASK_QUEUE,
        retry_policy=RetryPolicy(maximum_attempts=1),
    )
    await wf_handle.result()

    # Each subscription -> 2 recipients => 4 email calls expected
    assert mock_send_email.call_count == 4
    delivered_ids = {args[0][1].id for args in mock_send_email.call_args_list[::2]}  # every other call same sub
    assert delivered_ids == {sub.id for sub in subs_due}


@pytest.mark.asyncio
@patch("ee.tasks.subscriptions.send_email_subscription_report")
@patch("ee.tasks.subscriptions.generate_assets")
async def test_handle_subscription_value_change_workflow(
    mock_generate_assets: MagicMock,
    mock_send_email: MagicMock,
    temporal_client: Client,
    subscriptions_worker,
    team,
    user,
):
    """Workflow should notify only new addresses when subscription target value changes."""

    insight = await sync_to_async(Insight.objects.create)(team=team, short_id="xyz789", name="Insight")
    subscription = await sync_to_async(create_subscription)(
        team=team,
        insight=insight,
        created_by=user,
        target_value="old@org.com,new@org.com",
    )

    asset = await sync_to_async(ExportedAsset.objects.create)(
        team=team, insight_id=insight.id, export_format="image/png"
    )
    mock_generate_assets.return_value = [insight], [asset]

    wf_handle = await temporal_client.start_workflow(
        HandleSubscriptionValueChangeWorkflow.run,
        DeliverSubscriptionReportActivityInputs(
            subscription_id=subscription.id,
            previous_value="old@org.com",
            invite_message="Hello",
        ),
        id=str(uuid.uuid4()),
        task_queue=TASK_QUEUE,
    )
    await wf_handle.result()

    mock_send_email.assert_called_once()
    assert mock_send_email.call_args[0][0] == "new@org.com"
