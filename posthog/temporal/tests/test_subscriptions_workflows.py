import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from zoneinfo import ZoneInfo
from unittest.mock import MagicMock, call, patch
from django.conf import settings
from asgiref.sync import sync_to_async

import pytest
from freezegun import freeze_time
from temporalio.client import Client
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker, UnsandboxedWorkflowRunner

from ee.tasks.test.subscriptions.subscriptions_test_factory import create_subscription
from posthog.models.dashboard import Dashboard
from posthog.models.dashboard_tile import DashboardTile
from posthog.models.exported_asset import ExportedAsset
from posthog.models.insight import Insight
from posthog.models.instance_setting import set_instance_setting
from posthog.temporal.subscriptions.subscription_scheduling_workflow import (
    ScheduleAllSubscriptionsWorkflow,
    HandleSubscriptionValueChangeWorkflow,
    DeliverSubscriptionReportActivityInputs,
    deliver_subscription_report_activity,
    ScheduleAllSubscriptionsWorkflowInputs,
    fetch_due_subscriptions_activity,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.django_db(transaction=True)]


@pytest.fixture
async def subscriptions_worker(temporal_client: Client):
    """Spin up a Temporal worker for subscription workflows/activities."""

    async with Worker(
        temporal_client,
        task_queue=settings.TEMPORAL_TASK_QUEUE,
        workflows=[ScheduleAllSubscriptionsWorkflow, HandleSubscriptionValueChangeWorkflow],
        activities=[deliver_subscription_report_activity, fetch_due_subscriptions_activity],
        workflow_runner=UnsandboxedWorkflowRunner(),
    ):
        yield  # allow the test to run while the worker is active


@patch("ee.tasks.subscriptions.send_slack_subscription_report")
@patch("ee.tasks.subscriptions.send_email_subscription_report")
@patch("ee.tasks.subscriptions.generate_assets")
@freeze_time("2022-02-02T08:55:00.000Z")
@pytest.mark.asyncio
async def test_subscription_delivery_scheduling(
    mock_gen_assets: MagicMock,
    mock_send_email: MagicMock,
    mock_send_slack: MagicMock,
    temporal_client: Client,
    subscriptions_worker,
    team,
    user,
):
    """Workflow should schedule delivery only for subscriptions within the buffer window."""

    dashboard = await sync_to_async(Dashboard.objects.create)(team=team, name="private dashboard", created_by=user)
    insight = await sync_to_async(Insight.objects.create)(team=team, short_id="123456", name="My Test subscription")
    asset = await sync_to_async(ExportedAsset.objects.create)(
        team=team, insight_id=insight.id, export_format="image/png"
    )

    # Heavy dashboard – create extra tiles
    for i in range(10):
        tile_insight = await sync_to_async(Insight.objects.create)(
            team=team, short_id=f"{i}23456{i}", name=f"insight {i}"
        )
        await sync_to_async(DashboardTile.objects.create)(dashboard=dashboard, insight=tile_insight)

    mock_gen_assets.return_value = [insight], [asset]

    await sync_to_async(set_instance_setting)("EMAIL_HOST", "fake_host")
    await sync_to_async(set_instance_setting)("EMAIL_ENABLED", True)

    with freeze_time("2022-02-02T08:30:00.000Z"):
        subscriptions = [
            await sync_to_async(create_subscription)(team=team, insight=insight, created_by=user),
            await sync_to_async(create_subscription)(team=team, insight=insight, created_by=user),
            await sync_to_async(create_subscription)(team=team, dashboard=dashboard, created_by=user),
            await sync_to_async(create_subscription)(
                team=team,
                dashboard=dashboard,
                created_by=user,
                deleted=True,
            ),
        ]

    # Push one subscription outside buffer (+1h)
    subscriptions[2].start_date = datetime(2022, 1, 1, 10, 0, tzinfo=ZoneInfo("UTC"))
    await sync_to_async(subscriptions[2].save)()

    async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
        async with Worker(
            activity_environment.client,
            task_queue=settings.TEMPORAL_TASK_QUEUE,
            workflows=[ScheduleAllSubscriptionsWorkflow],
            activities=[deliver_subscription_report_activity, fetch_due_subscriptions_activity],
            workflow_runner=UnsandboxedWorkflowRunner(),
            activity_executor=ThreadPoolExecutor(max_workers=50),
            debug_mode=True,  # turn off sandbox/deadlock detector
        ):
            await activity_environment.client.execute_workflow(
                ScheduleAllSubscriptionsWorkflow.run,
                ScheduleAllSubscriptionsWorkflowInputs(),
                id=str(uuid.uuid4()),
                task_queue=settings.TEMPORAL_TASK_QUEUE,
            )

    assert mock_send_email.call_count == 0

    async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
        async with Worker(
            activity_environment.client,
            task_queue=settings.TEMPORAL_TASK_QUEUE,
            workflows=[ScheduleAllSubscriptionsWorkflow],
            activities=[deliver_subscription_report_activity, fetch_due_subscriptions_activity],
            workflow_runner=UnsandboxedWorkflowRunner(),
            activity_executor=ThreadPoolExecutor(max_workers=50),
            debug_mode=True,  # turn off sandbox/deadlock detector
        ):
            # Enable Temporal subscriptions for this team's organization
            with patch("posthoganalytics.feature_enabled", return_value=True):
                await activity_environment.client.execute_workflow(
                    ScheduleAllSubscriptionsWorkflow.run,
                    ScheduleAllSubscriptionsWorkflowInputs(),
                    id=str(uuid.uuid4()),
                    task_queue=settings.TEMPORAL_TASK_QUEUE,
                )

    # Each subscription has 2 recipients -> 4 emails expected (only first two subs)
    assert mock_send_email.call_count == 4
    delivered_sub_ids = {args[0][1].id for args in mock_send_email.call_args_list[::2]}
    assert delivered_sub_ids == {subscriptions[0].id, subscriptions[1].id}


@patch("posthoganalytics.feature_enabled", return_value=True)
@patch("ee.tasks.subscriptions.send_slack_subscription_report")
@patch("ee.tasks.subscriptions.send_email_subscription_report")
@patch("ee.tasks.subscriptions.generate_assets")
@freeze_time("2022-02-02T08:55:00.000Z")
@pytest.mark.asyncio
async def test_does_not_schedule_subscription_if_item_is_deleted(
    mock_gen_assets: MagicMock,
    mock_send_email: MagicMock,
    mock_send_slack: MagicMock,
    temporal_client: Client,
    subscriptions_worker,
    team,
    user,
):
    dashboard = await sync_to_async(Dashboard.objects.create)(team=team, name="private dashboard", created_by=user)
    insight = await sync_to_async(Insight.objects.create)(team=team, short_id="123456", name="My Test subscription")

    await sync_to_async(create_subscription)(
        team=team,
        insight=insight,
        created_by=user,
        target_type="slack",
        target_value="C12345|#test-channel",
    )

    await sync_to_async(create_subscription)(
        team=team,
        dashboard=dashboard,
        created_by=user,
        target_type="slack",
        target_value="C12345|#test-channel",
    )

    # Mark source items deleted
    insight.deleted = True
    dashboard.deleted = True
    await sync_to_async(insight.save)()
    await sync_to_async(dashboard.save)()

    async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
        async with Worker(
            activity_environment.client,
            task_queue=settings.TEMPORAL_TASK_QUEUE,
            workflows=[ScheduleAllSubscriptionsWorkflow],
            activities=[deliver_subscription_report_activity, fetch_due_subscriptions_activity],
            workflow_runner=UnsandboxedWorkflowRunner(),
            activity_executor=ThreadPoolExecutor(max_workers=50),
            debug_mode=True,  # turn off sandbox/deadlock detector
        ):
            await activity_environment.client.execute_workflow(
                ScheduleAllSubscriptionsWorkflow.run,
                ScheduleAllSubscriptionsWorkflowInputs(),
                id=str(uuid.uuid4()),
                task_queue=settings.TEMPORAL_TASK_QUEUE,
            )

    assert mock_send_email.call_count == 0 and mock_send_slack.call_count == 0


@patch("posthoganalytics.feature_enabled", return_value=True)
@patch("ee.tasks.subscriptions.send_email_subscription_report")
@patch("ee.tasks.subscriptions.generate_assets")
@pytest.mark.asyncio
async def test_handle_subscription_value_change_email(
    mock_gen_assets: MagicMock,
    mock_send_email: MagicMock,
    temporal_client: Client,
    subscriptions_worker,
    team,
    user,
):
    insight = await sync_to_async(Insight.objects.create)(team=team, short_id="xyz789", name="Insight")
    asset = await sync_to_async(ExportedAsset.objects.create)(
        team=team, insight_id=insight.id, export_format="image/png"
    )

    subscription = await sync_to_async(create_subscription)(
        team=team,
        insight=insight,
        created_by=user,
        target_value="test_existing@posthog.com,test_new@posthog.com",
    )

    mock_gen_assets.return_value = [insight], [asset]

    async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
        async with Worker(
            activity_environment.client,
            task_queue=settings.TEMPORAL_TASK_QUEUE,
            workflows=[HandleSubscriptionValueChangeWorkflow],
            activities=[deliver_subscription_report_activity],
            workflow_runner=UnsandboxedWorkflowRunner(),
            activity_executor=ThreadPoolExecutor(max_workers=50),
            debug_mode=True,  # turn off sandbox/deadlock detector
        ):
            await activity_environment.client.execute_workflow(
                HandleSubscriptionValueChangeWorkflow.run,
                DeliverSubscriptionReportActivityInputs(
                    subscription_id=subscription.id,
                    previous_value="test_existing@posthog.com",
                    invite_message="My invite message",
                ),
                id=str(uuid.uuid4()),
                task_queue=settings.TEMPORAL_TASK_QUEUE,
            )

    # Only new address should be emailed
    assert mock_send_email.call_count == 1
    assert mock_send_email.call_args_list == [
        call(
            "test_new@posthog.com",
            subscription,
            [asset],
            invite_message="My invite message",
            total_asset_count=1,
        )
    ]


@patch("posthoganalytics.feature_enabled", return_value=True)
@patch("ee.tasks.subscriptions.send_slack_subscription_report")
@patch("ee.tasks.subscriptions.generate_assets")
@pytest.mark.asyncio
async def test_deliver_subscription_report_slack(
    mock_gen_assets: MagicMock,
    mock_send_slack: MagicMock,
    temporal_client: Client,
    subscriptions_worker,
    team,
    user,
):
    insight = await sync_to_async(Insight.objects.create)(team=team, short_id="abc999", name="Insight")
    asset = await sync_to_async(ExportedAsset.objects.create)(
        team=team, insight_id=insight.id, export_format="image/png"
    )

    subscription = await sync_to_async(create_subscription)(
        team=team,
        insight=insight,
        created_by=user,
        target_type="slack",
        target_value="C12345|#test-channel",
    )

    mock_gen_assets.return_value = [insight], [asset]

    async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
        async with Worker(
            activity_environment.client,
            task_queue=settings.TEMPORAL_TASK_QUEUE,
            workflows=[HandleSubscriptionValueChangeWorkflow],
            activities=[deliver_subscription_report_activity],
            workflow_runner=UnsandboxedWorkflowRunner(),
            activity_executor=ThreadPoolExecutor(max_workers=50),
            debug_mode=True,  # turn off sandbox/deadlock detector
        ):
            await activity_environment.client.execute_workflow(
                HandleSubscriptionValueChangeWorkflow.run,
                DeliverSubscriptionReportActivityInputs(subscription_id=subscription.id),
                id=str(uuid.uuid4()),
                task_queue=settings.TEMPORAL_TASK_QUEUE,
            )

    assert mock_send_slack.call_count == 1
    assert mock_send_slack.call_args_list == [
        call(subscription, [asset], total_asset_count=1, is_new_subscription=False)
    ]
