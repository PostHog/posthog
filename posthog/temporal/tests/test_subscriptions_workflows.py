import uuid
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any, cast
from zoneinfo import ZoneInfo

import pytest
from freezegun import freeze_time
from unittest.mock import AsyncMock, MagicMock, patch

from django.conf import settings

import pytest_asyncio
from asgiref.sync import sync_to_async
from temporalio.client import Client
from temporalio.testing import ActivityEnvironment, WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.hogql.errors import QueryError

from posthog.errors import CHQueryErrorS3Error
from posthog.models.exported_asset import ExportedAsset
from posthog.models.insight import Insight
from posthog.models.instance_setting import set_instance_setting
from posthog.models.subscription import SubscriptionDelivery
from posthog.slo.types import SloArea, SloConfig, SloOperation, SloOutcome
from posthog.tasks.exports.failure_handler import ExcelColumnLimitExceeded
from posthog.temporal.common.slo_interceptor import SloInterceptor
from posthog.temporal.exports.activities import export_asset_activity
from posthog.temporal.subscriptions.activities import (
    advance_next_delivery_date,
    create_delivery_record,
    create_export_assets,
    deliver_subscription,
    fetch_due_subscriptions_activity,
    update_delivery_record,
)
from posthog.temporal.subscriptions.types import (
    CreateDeliveryRecordInputs,
    CreateExportAssetsInputs,
    DeliverSubscriptionInputs,
    DeliveryStatus,
    ProcessSubscriptionWorkflowInputs,
    ScheduleAllSubscriptionsWorkflowInputs,
    SubscriptionTriggerType,
    TrackedSubscriptionInputs,
    UpdateDeliveryRecordInputs,
)
from posthog.temporal.subscriptions.workflows import (
    HandleSubscriptionValueChangeWorkflow,
    ProcessSubscriptionWorkflow,
    ScheduleAllSubscriptionsWorkflow,
)

from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.models.dashboard_tile import DashboardTile

from ee.tasks.subscriptions.slack_subscriptions import SlackDeliveryResult
from ee.tasks.test.subscriptions.subscriptions_test_factory import create_subscription

pytestmark = [pytest.mark.asyncio, pytest.mark.django_db(transaction=True)]

SUBSCRIPTION_SCHEDULE_ACTIVITIES: Sequence[Callable[..., Any]] = cast(
    Sequence[Callable[..., Any]],
    [
        fetch_due_subscriptions_activity,
        create_delivery_record,
        create_export_assets,
        export_asset_activity,
        deliver_subscription,
        update_delivery_record,
        advance_next_delivery_date,
    ],
)

SUBSCRIPTION_PROCESS_ACTIVITIES: Sequence[Callable[..., Any]] = cast(
    Sequence[Callable[..., Any]],
    [
        create_delivery_record,
        create_export_assets,
        export_asset_activity,
        deliver_subscription,
        update_delivery_record,
        advance_next_delivery_date,
    ],
)


@pytest_asyncio.fixture
async def subscriptions_worker(temporal_client: Client):
    """Spin up a Temporal worker for subscription workflows/activities."""

    async with Worker(
        temporal_client,
        task_queue=settings.TEMPORAL_TASK_QUEUE,
        workflows=[
            ScheduleAllSubscriptionsWorkflow,
            HandleSubscriptionValueChangeWorkflow,
            ProcessSubscriptionWorkflow,
        ],
        activities=SUBSCRIPTION_SCHEDULE_ACTIVITIES,
        interceptors=[SloInterceptor()],
        workflow_runner=UnsandboxedWorkflowRunner(),
    ):
        yield  # allow the test to run while the worker is active


@patch("posthog.temporal.exports.activities.exporter")
@patch("posthog.slo.events.posthoganalytics")
@patch("ee.tasks.subscriptions.get_metric_meter")
@patch("posthog.temporal.subscriptions.activities.send_email_subscription_report")
@freeze_time("2022-02-02T08:55:00.000Z")
@pytest.mark.asyncio
async def test_subscription_delivery_scheduling(
    mock_send_email: MagicMock,
    mock_metric_meter: MagicMock,
    mock_analytics: MagicMock,
    mock_exporter: MagicMock,
    temporal_client: Client,
    subscriptions_worker,
    team,
    user,
):
    dashboard = await sync_to_async(Dashboard.objects.create)(team=team, name="private dashboard", created_by=user)
    insight = await sync_to_async(Insight.objects.create)(team=team, short_id="123456", name="My Test subscription")

    # Heavy dashboard – create extra tiles
    for i in range(10):
        tile_insight = await sync_to_async(Insight.objects.create)(
            team=team, short_id=f"{i}23456{i}", name=f"insight {i}"
        )
        await sync_to_async(DashboardTile.objects.create)(dashboard=dashboard, insight=tile_insight)

    def fake_export(asset_obj, **kwargs):
        asset_obj.content_location = "s3://bucket/test.png"
        asset_obj.save(update_fields=["content_location"])

    mock_exporter.export_asset_direct = fake_export

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
            workflows=[ScheduleAllSubscriptionsWorkflow, ProcessSubscriptionWorkflow],
            activities=SUBSCRIPTION_SCHEDULE_ACTIVITIES,
            interceptors=[SloInterceptor()],
            workflow_runner=UnsandboxedWorkflowRunner(),
            activity_executor=ThreadPoolExecutor(max_workers=50),
            debug_mode=True,
        ):
            await activity_environment.client.execute_workflow(
                ScheduleAllSubscriptionsWorkflow.run,
                ScheduleAllSubscriptionsWorkflowInputs(),
                id=str(uuid.uuid4()),
                task_queue=settings.TEMPORAL_TASK_QUEUE,
            )

    # Each subscription has 2 recipients -> 4 emails expected (only first two subs within buffer)
    assert mock_send_email.call_count == 4
    delivered_sub_ids = {args[0][1].id for args in mock_send_email.call_args_list}
    assert delivered_sub_ids == {subscriptions[0].id, subscriptions[1].id}


@patch("posthog.temporal.exports.activities.exporter")
@patch("posthog.slo.events.posthoganalytics")
@patch("ee.tasks.subscriptions.get_metric_meter")
@patch("posthog.temporal.subscriptions.activities.get_slack_integration_for_team", return_value=None)
@patch("posthog.temporal.subscriptions.activities.send_email_subscription_report")
@freeze_time("2022-02-02T08:55:00.000Z")
@pytest.mark.asyncio
async def test_does_not_schedule_subscription_if_item_is_deleted(
    mock_send_email: MagicMock,
    mock_send_slack: MagicMock,
    mock_metric_meter: MagicMock,
    mock_analytics: MagicMock,
    mock_exporter: MagicMock,
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
            workflows=[ScheduleAllSubscriptionsWorkflow, ProcessSubscriptionWorkflow],
            activities=SUBSCRIPTION_SCHEDULE_ACTIVITIES,
            interceptors=[SloInterceptor()],
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


@patch("posthog.temporal.exports.activities.exporter")
@patch("posthog.slo.events.posthoganalytics")
@patch("ee.tasks.subscriptions.get_metric_meter")
@patch("posthog.temporal.subscriptions.activities.send_email_subscription_report")
@pytest.mark.asyncio
async def test_handle_subscription_value_change_email(
    mock_send_email: MagicMock,
    mock_metric_meter: MagicMock,
    mock_analytics: MagicMock,
    mock_exporter: MagicMock,
    temporal_client: Client,
    subscriptions_worker,
    team,
    user,
):
    insight = await sync_to_async(Insight.objects.create)(team=team, short_id="xyz789", name="Insight")

    subscription = await sync_to_async(create_subscription)(
        team=team,
        insight=insight,
        created_by=user,
        target_value="test_existing@posthog.com,test_new@posthog.com",
    )

    def fake_export(asset_obj, **kwargs):
        asset_obj.content_location = "s3://bucket/change.png"
        asset_obj.save(update_fields=["content_location"])

    mock_exporter.export_asset_direct = fake_export

    async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
        async with Worker(
            activity_environment.client,
            task_queue=settings.TEMPORAL_TASK_QUEUE,
            workflows=[HandleSubscriptionValueChangeWorkflow, ProcessSubscriptionWorkflow],
            activities=SUBSCRIPTION_PROCESS_ACTIVITIES,
            interceptors=[SloInterceptor()],
            workflow_runner=UnsandboxedWorkflowRunner(),
            activity_executor=ThreadPoolExecutor(max_workers=50),
            debug_mode=True,
        ):
            await activity_environment.client.execute_workflow(
                HandleSubscriptionValueChangeWorkflow.run,
                ProcessSubscriptionWorkflowInputs(
                    subscription_id=subscription.id,
                    team_id=subscription.team_id,
                    distinct_id=str(subscription.created_by.distinct_id),  # type: ignore[union-attr]
                    previous_value="test_existing@posthog.com",
                    invite_message="My invite message",
                ),
                id=str(uuid.uuid4()),
                task_queue=settings.TEMPORAL_TASK_QUEUE,
            )

    # Only new address should be emailed
    assert mock_send_email.call_count == 1
    assert mock_send_email.call_args_list[0][0][0] == "test_new@posthog.com"

    # SLO events emitted exactly once (child only, not parent)
    started_calls = [
        c for c in mock_analytics.capture.call_args_list if c.kwargs.get("event") == "slo_operation_started"
    ]
    assert len(started_calls) == 1

    completed_calls = [
        c for c in mock_analytics.capture.call_args_list if c.kwargs.get("event") == "slo_operation_completed"
    ]
    assert len(completed_calls) == 1
    assert completed_calls[0].kwargs["properties"]["outcome"] == SloOutcome.SUCCESS


@patch("posthog.temporal.subscriptions.activities.send_slack_message_with_integration_async", new_callable=AsyncMock)
@patch("posthog.temporal.subscriptions.activities.get_slack_integration_for_team")
@patch("posthog.temporal.exports.activities.exporter")
@patch("posthog.slo.events.posthoganalytics")
@patch("ee.tasks.subscriptions.get_metric_meter")
@pytest.mark.asyncio
async def test_deliver_subscription_report_slack(
    mock_metric_meter: MagicMock,
    mock_analytics: MagicMock,
    mock_exporter: MagicMock,
    mock_get_slack: MagicMock,
    mock_send_slack_async: AsyncMock,
    temporal_client: Client,
    subscriptions_worker,
    team,
    user,
):
    mock_integration = MagicMock()
    mock_integration.kind = "slack"
    mock_get_slack.return_value = mock_integration
    mock_send_slack_async.return_value = SlackDeliveryResult(
        main_message_sent=True,
        total_thread_messages=0,
        failed_thread_message_indices=[],
    )

    insight = await sync_to_async(Insight.objects.create)(team=team, short_id="abc999", name="Insight")

    subscription = await sync_to_async(create_subscription)(
        team=team,
        insight=insight,
        created_by=user,
        target_type="slack",
        target_value="C12345|#test-channel",
    )

    def fake_export(asset_obj, **kwargs):
        asset_obj.content_location = "s3://bucket/slack.png"
        asset_obj.save(update_fields=["content_location"])

    mock_exporter.export_asset_direct = fake_export

    async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
        async with Worker(
            activity_environment.client,
            task_queue=settings.TEMPORAL_TASK_QUEUE,
            workflows=[HandleSubscriptionValueChangeWorkflow, ProcessSubscriptionWorkflow],
            activities=SUBSCRIPTION_PROCESS_ACTIVITIES,
            interceptors=[SloInterceptor()],
            workflow_runner=UnsandboxedWorkflowRunner(),
            activity_executor=ThreadPoolExecutor(max_workers=50),
            debug_mode=True,
        ):
            await activity_environment.client.execute_workflow(
                HandleSubscriptionValueChangeWorkflow.run,
                ProcessSubscriptionWorkflowInputs(
                    subscription_id=subscription.id,
                    team_id=subscription.team_id,
                    distinct_id=str(subscription.created_by.distinct_id),  # type: ignore[union-attr]
                ),
                id=str(uuid.uuid4()),
                task_queue=settings.TEMPORAL_TASK_QUEUE,
            )

    assert mock_send_slack_async.await_count == 1


@patch("posthog.temporal.subscriptions.activities.build_insight_delivery_snapshot")
@patch("posthog.temporal.subscriptions.activities.get_slack_integration_for_team", return_value=None)
@freeze_time("2022-02-02T08:55:00.000Z")
@pytest.mark.asyncio
async def test_process_subscription_records_missing_slack_integration_failure(
    mock_get_slack: MagicMock,
    mock_build_snapshot: MagicMock,
    temporal_client: Client,
    team,
    user,
):
    insight = await sync_to_async(Insight.objects.create)(team=team, short_id="slk001", name="Slack fail")
    mock_build_snapshot.return_value = {
        "id": insight.id,
        "short_id": str(insight.short_id),
        "name": insight.name or "",
        "dashboard_tile_id": None,
        "query_hash": "mock_cache_key",
        "cache_key": "mock_cache_key",
        "query_results": {"result": []},
    }
    subscription = await sync_to_async(create_subscription)(
        team=team,
        insight=insight,
        created_by=user,
        target_type="slack",
        target_value="C12345|#test-channel",
    )
    await sync_to_async(ExportedAsset.objects.create)(
        team=team,
        insight=insight,
        export_format="image/png",
        content_location="s3://bucket/slack-fail.png",
    )

    with pytest.raises(Exception):
        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with Worker(
                env.client,
                task_queue=settings.TEMPORAL_TASK_QUEUE,
                workflows=[ProcessSubscriptionWorkflow],
                activities=SUBSCRIPTION_PROCESS_ACTIVITIES,
                interceptors=[SloInterceptor()],
                workflow_runner=UnsandboxedWorkflowRunner(),
                activity_executor=ThreadPoolExecutor(max_workers=10),
                debug_mode=True,
            ):
                await env.client.execute_workflow(
                    ProcessSubscriptionWorkflow.run,
                    TrackedSubscriptionInputs(
                        subscription_id=subscription.id,
                        team_id=subscription.team_id,
                        distinct_id=str(subscription.created_by.distinct_id),  # type: ignore[union-attr]
                    ),
                    id=str(uuid.uuid4()),
                    task_queue=settings.TEMPORAL_TASK_QUEUE,
                )

    row = await sync_to_async(SubscriptionDelivery.objects.filter(subscription_id=subscription.id).latest)("created_at")
    assert row.status == SubscriptionDelivery.Status.FAILED
    assert row.recipient_results == [
        {
            "recipient": "C12345|#test-channel",
            "status": "failed",
            "error": {
                "message": "No Slack integration configured",
                "type": "missing_integration",
            },
        }
    ]
    mock_get_slack.assert_called_once_with(subscription.team_id)


@patch("posthog.slo.events.posthoganalytics")
@freeze_time("2022-02-02T08:55:00.000Z")
@pytest.mark.asyncio
async def test_create_export_assets_creates_exported_assets(
    mock_analytics: MagicMock,
    temporal_client: Client,
    team,
    user,
):
    insight = await sync_to_async(Insight.objects.create)(team=team, short_id="prep01", name="Prep Test")
    subscription = await sync_to_async(create_subscription)(team=team, insight=insight, created_by=user)

    env = ActivityEnvironment()
    result = await env.run(
        create_export_assets,
        CreateExportAssetsInputs(subscription_id=subscription.id),
    )

    assert len(result.exported_asset_ids) == 1
    assert result.team_id == team.id

    asset = await sync_to_async(ExportedAsset.objects.get)(pk=result.exported_asset_ids[0])
    assert asset.team_id == team.id
    assert asset.insight_id == insight.id
    assert asset.export_format == "image/png"

    # SLO started is emitted by the interceptor, not this activity
    mock_analytics.capture.assert_not_called()


@patch("posthog.temporal.subscriptions.activities.build_insight_delivery_snapshot")
@patch("posthog.slo.events.posthoganalytics")
@freeze_time("2022-02-02T08:55:00.000Z")
@pytest.mark.asyncio
async def test_create_export_assets_includes_insight_snapshots(
    mock_analytics: MagicMock,
    mock_build_snapshot: MagicMock,
    temporal_client: Client,
    team,
    user,
):
    mock_build_snapshot.return_value = {
        "id": 1,
        "short_id": "snap01",
        "name": "Snap Test",
        "dashboard_tile_id": None,
        "query_hash": "cache_key_test",
        "cache_key": "cache_key_test",
        "query_results": {"result": []},
    }
    insight = await sync_to_async(Insight.objects.create)(team=team, short_id="prep01", name="Prep Test")
    subscription = await sync_to_async(create_subscription)(team=team, insight=insight, created_by=user)

    env = ActivityEnvironment()
    result = await env.run(
        create_export_assets,
        CreateExportAssetsInputs(subscription_id=subscription.id),
    )

    assert len(result.exported_asset_ids) == 1
    assert len(result.insight_snapshots) == 1
    assert result.insight_snapshots[0]["query_hash"] == "cache_key_test"
    mock_build_snapshot.assert_called_once()
    mock_analytics.capture.assert_not_called()


@freeze_time("2022-02-02T08:55:00.000Z")
@pytest.mark.asyncio
async def test_create_delivery_record_persists_row_and_idempotency_key_dedupes(team, user):
    insight = await sync_to_async(Insight.objects.create)(team=team, short_id="delrec01", name="Delivery record")
    subscription = await sync_to_async(create_subscription)(team=team, insight=insight, created_by=user)

    env = ActivityEnvironment()
    inputs = CreateDeliveryRecordInputs(
        subscription_id=subscription.id,
        team_id=team.id,
        trigger_type=SubscriptionTriggerType.SCHEDULED,
        temporal_workflow_id="wf-delivery-1",
        idempotency_key="idem-dedupe",
        scheduled_at="2022-02-02T08:55:00+00:00",
    )
    delivery_id = await env.run(create_delivery_record, inputs)

    row = await sync_to_async(SubscriptionDelivery.objects.get)(pk=delivery_id)
    assert row.subscription_id == subscription.id
    assert row.team_id == team.id
    assert row.status == SubscriptionDelivery.Status.STARTING
    assert row.idempotency_key == "idem-dedupe"
    assert row.temporal_workflow_id == "wf-delivery-1"
    assert row.trigger_type == SubscriptionTriggerType.SCHEDULED
    assert row.scheduled_at is not None
    assert row.content_snapshot["total_insight_count"] == 0
    assert len(row.content_snapshot["insights"]) == 1
    assert row.content_snapshot["insights"][0]["short_id"] == "delrec01"

    inputs_retry = CreateDeliveryRecordInputs(
        subscription_id=subscription.id,
        team_id=team.id,
        trigger_type=SubscriptionTriggerType.SCHEDULED,
        temporal_workflow_id="wf-delivery-retry",
        idempotency_key="idem-dedupe",
        scheduled_at="2022-02-02T08:55:00+00:00",
    )
    delivery_id_again = await env.run(create_delivery_record, inputs_retry)
    assert delivery_id_again == delivery_id
    assert await sync_to_async(SubscriptionDelivery.objects.filter(idempotency_key="idem-dedupe").count)() == 1
    row_after = await sync_to_async(SubscriptionDelivery.objects.get)(pk=delivery_id)
    assert row_after.temporal_workflow_id == "wf-delivery-1"


@freeze_time("2022-02-02T08:55:00.000Z")
@pytest.mark.asyncio
async def test_update_delivery_record_merges_snapshot_and_finalizes(team, user):
    insight = await sync_to_async(Insight.objects.create)(team=team, short_id="upd01", name="Update delivery")
    subscription = await sync_to_async(create_subscription)(team=team, insight=insight, created_by=user)

    env = ActivityEnvironment()
    delivery_id = await env.run(
        create_delivery_record,
        CreateDeliveryRecordInputs(
            subscription_id=subscription.id,
            team_id=team.id,
            trigger_type=SubscriptionTriggerType.MANUAL,
            temporal_workflow_id="wf-upd",
            idempotency_key="idem-upd",
            scheduled_at=None,
        ),
    )

    await env.run(
        update_delivery_record,
        UpdateDeliveryRecordInputs(
            delivery_id=delivery_id,
            status=DeliveryStatus.COMPLETED,
            exported_asset_ids=[101, 102],
            content_snapshot={
                "total_insight_count": 1,
                "insights": [{"id": 99, "short_id": "x", "name": "snap", "query_hash": "qh"}],
            },
            recipient_results=[{"recipient": "r@example.com", "status": "success"}],
            error=None,
            finished=True,
        ),
    )

    row = await sync_to_async(SubscriptionDelivery.objects.get)(pk=delivery_id)
    assert row.status == SubscriptionDelivery.Status.COMPLETED
    assert row.exported_asset_ids == [101, 102]
    assert row.recipient_results == [{"recipient": "r@example.com", "status": "success"}]
    assert row.content_snapshot["total_insight_count"] == 1
    assert row.content_snapshot["insights"] == [{"id": 99, "short_id": "x", "name": "snap", "query_hash": "qh"}]
    assert "dashboard" in row.content_snapshot
    assert row.finished_at is not None


@freeze_time("2022-02-02T08:55:00.000Z")
@pytest.mark.asyncio
async def test_update_delivery_record_none_omits_collection_fields(team, user):
    insight = await sync_to_async(Insight.objects.create)(team=team, short_id="omit01", name="Omit fields")
    subscription = await sync_to_async(create_subscription)(team=team, insight=insight, created_by=user)

    env = ActivityEnvironment()
    delivery_id = await env.run(
        create_delivery_record,
        CreateDeliveryRecordInputs(
            subscription_id=subscription.id,
            team_id=team.id,
            trigger_type=SubscriptionTriggerType.MANUAL,
            temporal_workflow_id="wf-omit",
            idempotency_key="idem-omit",
            scheduled_at=None,
        ),
    )

    await env.run(
        update_delivery_record,
        UpdateDeliveryRecordInputs(
            delivery_id=delivery_id,
            status=DeliveryStatus.COMPLETED,
            exported_asset_ids=[42],
            recipient_results=[{"recipient": "a@b.com", "status": "success"}],
            finished=True,
        ),
    )

    await env.run(
        update_delivery_record,
        UpdateDeliveryRecordInputs(
            delivery_id=delivery_id,
            status=DeliveryStatus.FAILED,
            error={"message": "downstream", "type": "RuntimeError"},
            finished=True,
        ),
    )

    row = await sync_to_async(SubscriptionDelivery.objects.get)(pk=delivery_id)
    assert row.status == SubscriptionDelivery.Status.FAILED
    assert row.exported_asset_ids == [42]
    assert row.recipient_results == [{"recipient": "a@b.com", "status": "success"}]


@freeze_time("2022-02-02T08:55:00.000Z")
@pytest.mark.asyncio
async def test_update_delivery_record_empty_lists_persist(team, user):
    insight = await sync_to_async(Insight.objects.create)(team=team, short_id="empty01", name="Empty lists")
    subscription = await sync_to_async(create_subscription)(team=team, insight=insight, created_by=user)

    env = ActivityEnvironment()
    delivery_id = await env.run(
        create_delivery_record,
        CreateDeliveryRecordInputs(
            subscription_id=subscription.id,
            team_id=team.id,
            trigger_type=SubscriptionTriggerType.MANUAL,
            temporal_workflow_id="wf-empty",
            idempotency_key="idem-empty",
            scheduled_at=None,
        ),
    )

    await env.run(
        update_delivery_record,
        UpdateDeliveryRecordInputs(
            delivery_id=delivery_id,
            status=DeliveryStatus.COMPLETED,
            exported_asset_ids=[1, 2],
            recipient_results=[{"recipient": "x@y.com", "status": "success"}],
            finished=True,
        ),
    )

    await env.run(
        update_delivery_record,
        UpdateDeliveryRecordInputs(
            delivery_id=delivery_id,
            status=DeliveryStatus.COMPLETED,
            exported_asset_ids=[],
            recipient_results=[],
            finished=True,
        ),
    )

    row = await sync_to_async(SubscriptionDelivery.objects.get)(pk=delivery_id)
    assert row.exported_asset_ids == []
    assert row.recipient_results == []


@patch("posthog.slo.events.posthoganalytics")
@freeze_time("2022-02-02T08:55:00.000Z")
@pytest.mark.asyncio
async def test_create_export_assets_dashboard_with_multiple_insights(
    mock_analytics: MagicMock,
    temporal_client: Client,
    team,
    user,
):
    dashboard = await sync_to_async(Dashboard.objects.create)(team=team, name="Multi-insight", created_by=user)
    for i in range(3):
        insight = await sync_to_async(Insight.objects.create)(team=team, short_id=f"prep{i:02d}", name=f"Insight {i}")
        await sync_to_async(DashboardTile.objects.create)(dashboard=dashboard, insight=insight)

    subscription = await sync_to_async(create_subscription)(team=team, dashboard=dashboard, created_by=user)

    env = ActivityEnvironment()
    result = await env.run(
        create_export_assets,
        CreateExportAssetsInputs(subscription_id=subscription.id),
    )

    assert len(result.exported_asset_ids) == 3
    # SLO started is emitted by the interceptor, not this activity
    mock_analytics.capture.assert_not_called()


@freeze_time("2022-02-02T08:55:00.000Z")
@pytest.mark.asyncio
async def test_create_export_assets_excludes_deleted_insights(team, user):
    dashboard = await sync_to_async(Dashboard.objects.create)(team=team, name="With deleted", created_by=user)
    for i in range(5):
        insight = await sync_to_async(Insight.objects.create)(
            team=team, short_id=f"del{i:02d}", name=f"Insight {i}", deleted=(i >= 2)
        )
        await sync_to_async(DashboardTile.objects.create)(dashboard=dashboard, insight=insight)

    subscription = await sync_to_async(create_subscription)(team=team, dashboard=dashboard, created_by=user)

    env = ActivityEnvironment()
    result = await env.run(
        create_export_assets,
        CreateExportAssetsInputs(subscription_id=subscription.id),
    )

    assert len(result.exported_asset_ids) == 2
    assert result.total_insight_count == 2


@freeze_time("2022-02-02T08:55:00.000Z")
@pytest.mark.asyncio
async def test_create_export_assets_raises_on_missing_resource(team, user):
    subscription = await sync_to_async(create_subscription)(team=team, created_by=user)

    env = ActivityEnvironment()
    with pytest.raises(Exception, match="There are no insights to be sent"):
        await env.run(
            create_export_assets,
            CreateExportAssetsInputs(subscription_id=subscription.id),
        )


@freeze_time("2022-02-02T08:55:00.000Z")
@pytest.mark.asyncio
async def test_create_export_assets_respects_max_asset_count(team, user):
    dashboard = await sync_to_async(Dashboard.objects.create)(team=team, name="Big dashboard", created_by=user)
    for i in range(10):
        insight = await sync_to_async(Insight.objects.create)(team=team, short_id=f"max{i:02d}", name=f"Insight {i}")
        await sync_to_async(DashboardTile.objects.create)(dashboard=dashboard, insight=insight)

    subscription = await sync_to_async(create_subscription)(team=team, dashboard=dashboard, created_by=user)

    env = ActivityEnvironment()
    result = await env.run(
        create_export_assets,
        CreateExportAssetsInputs(subscription_id=subscription.id, max_asset_count=3),
    )

    assert len(result.exported_asset_ids) == 3
    assert result.total_insight_count == 10


@freeze_time("2022-02-02T08:55:00.000Z")
@pytest.mark.asyncio
async def test_create_export_assets_empty_dashboard(team, user):
    dashboard = await sync_to_async(Dashboard.objects.create)(team=team, name="Empty", created_by=user)
    subscription = await sync_to_async(create_subscription)(team=team, dashboard=dashboard, created_by=user)

    env = ActivityEnvironment()
    result = await env.run(
        create_export_assets,
        CreateExportAssetsInputs(subscription_id=subscription.id),
    )

    assert result.exported_asset_ids == []
    assert result.total_insight_count == 0


@patch("ee.tasks.subscriptions.get_metric_meter")
@patch("posthog.temporal.subscriptions.activities.send_email_subscription_report")
@freeze_time("2022-02-02T08:55:00.000Z")
@pytest.mark.asyncio
async def test_deliver_subscription_sends_email(
    mock_send_email: MagicMock,
    mock_metric_meter: MagicMock,
    temporal_client: Client,
    team,
    user,
):
    insight = await sync_to_async(Insight.objects.create)(team=team, short_id="del01", name="Deliver Test")
    asset = await sync_to_async(ExportedAsset.objects.create)(
        team=team,
        insight=insight,
        export_format="image/png",
        content_location="s3://bucket/test.png",
    )
    # Factory default target_value is "test1@posthog.com,test2@posthog.com" (2 recipients)
    subscription = await sync_to_async(create_subscription)(team=team, insight=insight, created_by=user)

    env = ActivityEnvironment()
    await env.run(
        deliver_subscription,
        DeliverSubscriptionInputs(
            subscription_id=subscription.id,
            exported_asset_ids=[asset.id],
            total_insight_count=1,
        ),
    )

    assert mock_send_email.call_count == 2  # "test1@posthog.com" and "test2@posthog.com"


@patch("posthog.temporal.exports.activities.exporter")
@patch("posthog.slo.events.posthoganalytics")
@patch("ee.tasks.subscriptions.get_metric_meter")
@patch("posthog.temporal.subscriptions.activities.send_email_subscription_report")
@freeze_time("2022-02-02T08:55:00.000Z")
@pytest.mark.asyncio
async def test_deliver_subscription_workflow_end_to_end(
    mock_send_email: MagicMock,
    mock_metric_meter: MagicMock,
    mock_slo_analytics: MagicMock,
    mock_exporter: MagicMock,
    temporal_client: Client,
    team,
    user,
):
    insight = await sync_to_async(Insight.objects.create)(team=team, short_id="e2e01", name="E2E Test")
    subscription = await sync_to_async(create_subscription)(team=team, insight=insight, created_by=user)

    def fake_export(asset_obj, **kwargs):
        asset_obj.content_location = "s3://bucket/e2e.png"
        asset_obj.save(update_fields=["content_location"])

    mock_exporter.export_asset_direct = fake_export

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=settings.TEMPORAL_TASK_QUEUE,
            workflows=[ProcessSubscriptionWorkflow],
            activities=SUBSCRIPTION_PROCESS_ACTIVITIES,
            interceptors=[SloInterceptor()],
            workflow_runner=UnsandboxedWorkflowRunner(),
            activity_executor=ThreadPoolExecutor(max_workers=10),
            debug_mode=True,
        ):
            await env.client.execute_workflow(
                ProcessSubscriptionWorkflow.run,
                TrackedSubscriptionInputs(
                    subscription_id=subscription.id,
                    team_id=subscription.team_id,
                    distinct_id=str(subscription.created_by.distinct_id),  # type: ignore[union-attr]
                    slo=SloConfig(
                        operation=SloOperation.SUBSCRIPTION_DELIVERY,
                        area=SloArea.ANALYTIC_PLATFORM,
                        team_id=subscription.team_id,
                        resource_id=str(subscription.id),
                        distinct_id=str(subscription.created_by.distinct_id),  # type: ignore[union-attr]
                    ),
                ),
                id=str(uuid.uuid4()),
                task_queue=settings.TEMPORAL_TASK_QUEUE,
            )

    # 2 recipients
    assert mock_send_email.call_count == 2

    # Both started and completed events flow through posthog.slo.events
    started_calls = [
        c for c in mock_slo_analytics.capture.call_args_list if c.kwargs.get("event") == "slo_operation_started"
    ]
    assert len(started_calls) == 1

    completed_calls = [
        c for c in mock_slo_analytics.capture.call_args_list if c.kwargs.get("event") == "slo_operation_completed"
    ]
    assert len(completed_calls) == 1
    assert completed_calls[0].kwargs["properties"]["outcome"] == SloOutcome.SUCCESS


@patch("posthog.temporal.exports.activities.exporter")
@patch("posthog.slo.events.posthoganalytics")
@patch("ee.tasks.subscriptions.get_metric_meter")
@patch("posthog.temporal.subscriptions.activities.send_email_subscription_report")
@pytest.mark.asyncio
async def test_new_subscription_sends_invite_email(
    mock_send_email: MagicMock,
    mock_metric_meter: MagicMock,
    mock_analytics: MagicMock,
    mock_exporter: MagicMock,
    temporal_client: Client,
    subscriptions_worker,
    team,
    user,
):
    insight = await sync_to_async(Insight.objects.create)(team=team, short_id="inv01", name="Invite Test")
    subscription = await sync_to_async(create_subscription)(
        team=team,
        insight=insight,
        created_by=user,
        target_value="new_user@posthog.com",
    )
    original_next_delivery = subscription.next_delivery_date

    def fake_export(asset_obj, **kwargs):
        asset_obj.content_location = "s3://bucket/invite.png"
        asset_obj.save(update_fields=["content_location"])

    mock_exporter.export_asset_direct = fake_export

    async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
        async with Worker(
            activity_environment.client,
            task_queue=settings.TEMPORAL_TASK_QUEUE,
            workflows=[HandleSubscriptionValueChangeWorkflow, ProcessSubscriptionWorkflow],
            activities=SUBSCRIPTION_PROCESS_ACTIVITIES,
            interceptors=[SloInterceptor()],
            workflow_runner=UnsandboxedWorkflowRunner(),
            activity_executor=ThreadPoolExecutor(max_workers=50),
            debug_mode=True,
        ):
            await activity_environment.client.execute_workflow(
                HandleSubscriptionValueChangeWorkflow.run,
                ProcessSubscriptionWorkflowInputs(
                    subscription_id=subscription.id,
                    team_id=subscription.team_id,
                    distinct_id=str(subscription.created_by.distinct_id),  # type: ignore[union-attr]
                    previous_value="",
                    invite_message="Welcome!",
                ),
                id=str(uuid.uuid4()),
                task_queue=settings.TEMPORAL_TASK_QUEUE,
            )

    assert mock_send_email.call_count == 1
    call_args = mock_send_email.call_args
    assert call_args[0][0] == "new_user@posthog.com"
    assert call_args[1]["invite_message"] == "Welcome!"

    # next_delivery_date should NOT be updated for invite deliveries
    await sync_to_async(subscription.refresh_from_db)()
    assert subscription.next_delivery_date == original_next_delivery


@patch("posthog.temporal.exports.activities.exporter")
@patch("posthog.slo.events.posthoganalytics")
@patch("ee.tasks.subscriptions.get_metric_meter")
@patch("posthog.temporal.subscriptions.activities.send_email_subscription_report")
@pytest.mark.asyncio
async def test_manual_send_uses_regular_template_not_invite(
    mock_send_email: MagicMock,
    mock_metric_meter: MagicMock,
    mock_analytics: MagicMock,
    mock_exporter: MagicMock,
    temporal_client: Client,
    subscriptions_worker,
    team,
    user,
):
    insight = await sync_to_async(Insight.objects.create)(team=team, short_id="man01", name="Manual Test")
    subscription = await sync_to_async(create_subscription)(team=team, insight=insight, created_by=user)
    original_next_delivery = subscription.next_delivery_date

    def fake_export(asset_obj, **kwargs):
        asset_obj.content_location = "s3://bucket/manual.png"
        asset_obj.save(update_fields=["content_location"])

    mock_exporter.export_asset_direct = fake_export

    async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
        async with Worker(
            activity_environment.client,
            task_queue=settings.TEMPORAL_TASK_QUEUE,
            workflows=[HandleSubscriptionValueChangeWorkflow, ProcessSubscriptionWorkflow],
            activities=SUBSCRIPTION_PROCESS_ACTIVITIES,
            interceptors=[SloInterceptor()],
            workflow_runner=UnsandboxedWorkflowRunner(),
            activity_executor=ThreadPoolExecutor(max_workers=50),
            debug_mode=True,
        ):
            await activity_environment.client.execute_workflow(
                HandleSubscriptionValueChangeWorkflow.run,
                ProcessSubscriptionWorkflowInputs(
                    subscription_id=subscription.id,
                    team_id=subscription.team_id,
                    distinct_id=str(subscription.created_by.distinct_id),  # type: ignore[union-attr]
                    previous_value=None,
                    invite_message=None,
                    trigger_type=SubscriptionTriggerType.MANUAL,
                ),
                id=str(uuid.uuid4()),
                task_queue=settings.TEMPORAL_TASK_QUEUE,
            )

    # Should use regular template (invite_message=None means is_invite=False)
    assert mock_send_email.call_count == 2  # 2 recipients
    call_kwargs = mock_send_email.call_args[1]
    assert call_kwargs.get("invite_message") is None

    # next_delivery_date should NOT be updated for manual sends
    await sync_to_async(subscription.refresh_from_db)()
    assert subscription.next_delivery_date == original_next_delivery


@patch("posthog.temporal.exports.activities.exporter")
@patch("posthog.slo.events.posthoganalytics")
@patch("ee.tasks.subscriptions.get_metric_meter")
@patch("posthog.temporal.subscriptions.activities.send_email_subscription_report")
@freeze_time("2022-02-02T08:55:00.000Z")
@pytest.mark.asyncio
async def test_scheduled_delivery_updates_next_delivery_date(
    mock_send_email: MagicMock,
    mock_metric_meter: MagicMock,
    mock_slo_analytics: MagicMock,
    mock_exporter: MagicMock,
    temporal_client: Client,
    team,
    user,
):
    insight = await sync_to_async(Insight.objects.create)(team=team, short_id="sched1", name="Sched Test")
    subscription = await sync_to_async(create_subscription)(team=team, insight=insight, created_by=user)
    original_next_delivery = subscription.next_delivery_date

    def fake_export(asset_obj, **kwargs):
        asset_obj.content_location = "s3://bucket/sched.png"
        asset_obj.save(update_fields=["content_location"])

    mock_exporter.export_asset_direct = fake_export

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=settings.TEMPORAL_TASK_QUEUE,
            workflows=[ProcessSubscriptionWorkflow],
            activities=SUBSCRIPTION_PROCESS_ACTIVITIES,
            interceptors=[SloInterceptor()],
            workflow_runner=UnsandboxedWorkflowRunner(),
            activity_executor=ThreadPoolExecutor(max_workers=10),
            debug_mode=True,
        ):
            await env.client.execute_workflow(
                ProcessSubscriptionWorkflow.run,
                TrackedSubscriptionInputs(
                    subscription_id=subscription.id,
                    team_id=subscription.team_id,
                    distinct_id=str(subscription.created_by.distinct_id),  # type: ignore[union-attr]
                    trigger_type=SubscriptionTriggerType.SCHEDULED,
                    slo=SloConfig(
                        operation=SloOperation.SUBSCRIPTION_DELIVERY,
                        area=SloArea.ANALYTIC_PLATFORM,
                        team_id=subscription.team_id,
                        resource_id=str(subscription.id),
                        distinct_id=str(subscription.created_by.distinct_id),  # type: ignore[union-attr]
                    ),
                ),
                id=str(uuid.uuid4()),
                task_queue=settings.TEMPORAL_TASK_QUEUE,
            )

    # 2 recipients from factory default
    assert mock_send_email.call_count == 2
    for call in mock_send_email.call_args_list:
        assert call[1]["invite_message"] is None

    # next_delivery_date should be updated for scheduled deliveries
    await sync_to_async(subscription.refresh_from_db)()
    assert subscription.next_delivery_date != original_next_delivery


def _make_export_counter(fail_count: int, error_factory):
    """Create a fake export that fails `fail_count` times then succeeds."""
    state = {"calls": 0}

    def fake_export(asset_obj, **kwargs):
        state["calls"] += 1
        if state["calls"] <= fail_count:
            raise error_factory()
        asset_obj.content_location = "s3://bucket/ok.png"
        asset_obj.save(update_fields=["content_location"])

    return fake_export, state


@pytest.mark.parametrize(
    "error_factory,fail_count,expected_calls,expected_outcome",
    [
        (ExcelColumnLimitExceeded, 999, 1, SloOutcome.SUCCESS),
        (lambda: CHQueryErrorS3Error("S3 error", code=499), 2, 3, SloOutcome.SUCCESS),
        (lambda: QueryError("Invalid HogQL query"), 999, 1, SloOutcome.SUCCESS),
    ],
    ids=["user_error_slo_success", "transient_error_retries_then_succeeds", "user_query_error_no_retry"],
)
@patch("posthog.temporal.exports.activities.exporter")
@patch("posthog.slo.events.posthoganalytics")
@patch("ee.tasks.subscriptions.get_metric_meter")
@patch("posthog.temporal.subscriptions.activities.send_email_subscription_report")
@freeze_time("2022-02-02T08:55:00.000Z")
@pytest.mark.asyncio
async def test_export_error_slo_outcome(
    mock_send_email: MagicMock,
    mock_metric_meter: MagicMock,
    mock_slo_analytics: MagicMock,
    mock_exporter: MagicMock,
    temporal_client: Client,
    team,
    user,
    error_factory,
    fail_count: int,
    expected_calls: int,
    expected_outcome: SloOutcome,
):
    insight = await sync_to_async(Insight.objects.create)(team=team, short_id="slo01", name="SLO Test")
    subscription = await sync_to_async(create_subscription)(team=team, insight=insight, created_by=user)

    fake_export, state = _make_export_counter(fail_count, error_factory)
    mock_exporter.export_asset_direct = fake_export

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=settings.TEMPORAL_TASK_QUEUE,
            workflows=[ProcessSubscriptionWorkflow],
            activities=SUBSCRIPTION_PROCESS_ACTIVITIES,
            interceptors=[SloInterceptor()],
            workflow_runner=UnsandboxedWorkflowRunner(),
            activity_executor=ThreadPoolExecutor(max_workers=10),
            debug_mode=True,
        ):
            await env.client.execute_workflow(
                ProcessSubscriptionWorkflow.run,
                TrackedSubscriptionInputs(
                    subscription_id=subscription.id,
                    team_id=subscription.team_id,
                    distinct_id=str(subscription.created_by.distinct_id),  # type: ignore[union-attr]
                    slo=SloConfig(
                        operation=SloOperation.SUBSCRIPTION_DELIVERY,
                        area=SloArea.ANALYTIC_PLATFORM,
                        team_id=subscription.team_id,
                        resource_id=str(subscription.id),
                        distinct_id=str(subscription.created_by.distinct_id),  # type: ignore[union-attr]
                    ),
                ),
                id=str(uuid.uuid4()),
                task_queue=settings.TEMPORAL_TASK_QUEUE,
            )

    assert state["calls"] == expected_calls

    completed_calls = [
        c for c in mock_slo_analytics.capture.call_args_list if c.kwargs.get("event") == "slo_operation_completed"
    ]
    assert len(completed_calls) == 1
    assert completed_calls[0].kwargs["properties"]["outcome"] == expected_outcome


@pytest.mark.parametrize(
    "error_factory,expected_outcome,expected_error_type,expected_error_msg",
    [
        pytest.param(
            lambda: RuntimeError("ClickHouse connection timeout"),
            SloOutcome.FAILURE,
            "PartialExportFailure",
            "1 export(s) failed: RuntimeError",
            id="non_user_error_sets_slo_error_type",
        ),
        pytest.param(
            lambda: QueryError("Invalid HogQL query"),
            SloOutcome.SUCCESS,
            None,
            None,
            id="user_error_keeps_slo_success",
        ),
    ],
)
@patch("posthog.temporal.exports.activities.exporter")
@patch("posthog.slo.events.posthoganalytics")
@patch("ee.tasks.subscriptions.get_metric_meter")
@patch("posthog.temporal.subscriptions.activities.send_email_subscription_report")
@freeze_time("2022-02-02T08:55:00.000Z")
@pytest.mark.asyncio
async def test_partial_export_failure_delivers_successful_assets(
    mock_send_email: MagicMock,
    mock_metric_meter: MagicMock,
    mock_slo_analytics: MagicMock,
    mock_exporter: MagicMock,
    temporal_client: Client,
    team,
    user,
    error_factory,
    expected_outcome: SloOutcome,
    expected_error_type: str | None,
    expected_error_msg: str | None,
):
    dashboard = await sync_to_async(Dashboard.objects.create)(team=team, name="partial fail", created_by=user)
    insights = []
    for i in range(3):
        insight = await sync_to_async(Insight.objects.create)(team=team, short_id=f"pf{i:02d}", name=f"Insight {i}")
        await sync_to_async(DashboardTile.objects.create)(dashboard=dashboard, insight=insight)
        insights.append(insight)

    subscription = await sync_to_async(create_subscription)(team=team, dashboard=dashboard, created_by=user)

    fail_insight_id = insights[0].id

    def fake_export(asset_obj, **kwargs):
        if asset_obj.insight_id == fail_insight_id:
            raise error_factory()
        asset_obj.content_location = "s3://bucket/ok.png"
        asset_obj.save(update_fields=["content_location"])

    mock_exporter.export_asset_direct = fake_export

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=settings.TEMPORAL_TASK_QUEUE,
            workflows=[ProcessSubscriptionWorkflow],
            activities=SUBSCRIPTION_PROCESS_ACTIVITIES,
            interceptors=[SloInterceptor()],
            workflow_runner=UnsandboxedWorkflowRunner(),
            activity_executor=ThreadPoolExecutor(max_workers=10),
            debug_mode=True,
        ):
            await env.client.execute_workflow(
                ProcessSubscriptionWorkflow.run,
                TrackedSubscriptionInputs(
                    subscription_id=subscription.id,
                    team_id=subscription.team_id,
                    distinct_id=str(subscription.created_by.distinct_id),  # type: ignore[union-attr]
                    slo=SloConfig(
                        operation=SloOperation.SUBSCRIPTION_DELIVERY,
                        area=SloArea.ANALYTIC_PLATFORM,
                        team_id=subscription.team_id,
                        resource_id=str(subscription.id),
                        distinct_id=str(subscription.created_by.distinct_id),  # type: ignore[union-attr]
                    ),
                ),
                id=str(uuid.uuid4()),
                task_queue=settings.TEMPORAL_TASK_QUEUE,
            )

    # Delivery includes all assets (failed ones show placeholder in email)
    assert mock_send_email.call_count == 2  # 2 recipients from factory default
    for call in mock_send_email.call_args_list:
        delivered_assets = call[0][2]  # third positional arg is assets list
        assert len(delivered_assets) == 3

    completed_calls = [
        c for c in mock_slo_analytics.capture.call_args_list if c.kwargs.get("event") == "slo_operation_completed"
    ]
    assert len(completed_calls) == 1
    props = completed_calls[0].kwargs["properties"]
    assert props["outcome"] == expected_outcome
    assert props["assets_with_content"] == 2
    assert props["total_assets"] == 3

    # Non-user errors populate top-level error_type/error_message and asset_errors;
    # user errors are reclassified as SUCCESS and filtered out of both.
    if expected_error_type:
        assert props["error_type"] == expected_error_type
        assert props["error_message"] == expected_error_msg
        assert len(props["asset_errors"]) == 1
        assert "Traceback" in props["asset_errors"][0]["error_trace"]
    else:
        assert "error_type" not in props
        assert props["asset_errors"] == []
