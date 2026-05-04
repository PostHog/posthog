import json
import uuid
import dataclasses
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
from posthog.models.integration import Integration
from posthog.models.subscription import Subscription, SubscriptionDelivery
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
    validate_subscription_for_delivery,
)
from posthog.temporal.subscriptions.types import (
    CreateDeliveryRecordInputs,
    CreateExportAssetsInputs,
    CreateExportAssetsResult,
    DeliverSubscriptionInputs,
    DeliveryStatus,
    FetchDueSubscriptionsActivityInputs,
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
        validate_subscription_for_delivery,
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
        validate_subscription_for_delivery,
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
    integration = await sync_to_async(Integration.objects.create)(
        team=team,
        kind="slack",
        config={"team": {"id": "T123", "name": "Test"}},
    )

    subscription = await sync_to_async(create_subscription)(
        team=team,
        insight=insight,
        created_by=user,
        target_type="slack",
        target_value="C12345|#test-channel",
        integration_id=integration.id,
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


@patch("ee.tasks.subscriptions.auto_disable.send_notifications_for_disabled_subscription")
@patch("posthog.temporal.subscriptions.activities.build_insight_delivery_snapshot")
@patch("posthog.temporal.subscriptions.activities.get_slack_integration_for_team", return_value=None)
@freeze_time("2022-02-02T08:55:00.000Z")
@pytest.mark.asyncio
async def test_process_subscription_records_missing_slack_integration_failure(
    mock_get_slack: MagicMock,
    mock_build_snapshot: MagicMock,
    mock_send_notification: MagicMock,
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

    # Missing Slack integration_id is caught by the workflow's validation step
    # which auto-disables before the export pipeline runs. The team-fallback in
    # `deliver_subscription` is no longer reachable for this scenario.
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
    # Validate auto-disabled the sub: row is FAILED with the disable reason in
    # recipient_results so support/debugging can read the failure detail directly.
    assert row.status == SubscriptionDelivery.Status.FAILED
    assert row.recipient_results == [
        {
            "recipient": "C12345|#test-channel",
            "status": "failed",
            "error": {
                "message": "Slack integration disconnected",
                "type": "missing_integration",
            },
        }
    ]
    mock_get_slack.assert_not_called()

    # Subscription is auto-disabled and owner is notified.
    await sync_to_async(subscription.refresh_from_db)()
    assert subscription.enabled is False
    mock_send_notification.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case_label, target_type, target_value, expected_error",
    [
        (
            "missing_slack_integration",
            "slack",
            "C12345|#test-channel",
            {"message": "Slack integration disconnected", "type": "missing_integration"},
        ),
        (
            "unsupported_target",
            "webhook",
            "https://example.com/hook",
            {"message": "Unsupported delivery channel", "type": "unsupported_target"},
        ),
    ],
)
async def test_deliver_subscription_auto_disables_invalid_subscriptions(
    team, user, case_label, target_type, target_value, expected_error
):
    """Activity-level auto-disable for permanently-broken targets. `no_assets` is
    deliberately excluded — empty-assets-at-delivery is transient (the workflow short-
    circuits to SKIPPED before `deliver_subscription` runs when assets are genuinely
    deleted). See test_no_assets_does_not_auto_disable.
    """
    insight = await sync_to_async(Insight.objects.create)(team=team, short_id=f"dis-{case_label[:5]}", name=case_label)
    asset = await sync_to_async(ExportedAsset.objects.create)(
        team=team,
        insight=insight,
        export_format="image/png",
        content_location=f"s3://bucket/{case_label}.png",
    )
    subscription = await sync_to_async(create_subscription)(
        team=team,
        insight=insight,
        created_by=user,
        target_type=target_type,
        target_value=target_value,
        enabled=True,
    )

    env = ActivityEnvironment()

    with (
        patch("ee.tasks.subscriptions.auto_disable.send_notifications_for_disabled_subscription") as send_mock,
        # Always patched — only consulted on the slack branch, harmless otherwise.
        patch(
            "posthog.temporal.subscriptions.activities.get_slack_integration_for_team",
            return_value=None,
        ),
        patch("posthog.temporal.subscriptions.activities._capture_delivery_failed_event") as capture_mock,
    ):
        result = await env.run(
            deliver_subscription,
            DeliverSubscriptionInputs(
                subscription_id=subscription.id,
                exported_asset_ids=[asset.id],
                total_insight_count=1,
            ),
        )

    await sync_to_async(subscription.refresh_from_db)()
    assert subscription.enabled is False
    send_mock.assert_called_once()
    capture_mock.assert_called_once()
    # Must return cleanly — NOT raise
    assert result is not None
    assert result.recipient_results[0].status == "failed"
    assert result.recipient_results[0].error == expected_error


@pytest.mark.asyncio
async def test_no_assets_does_not_auto_disable(team, user):
    """Empty `assets` at delivery time is a transient export-pipeline failure
    (genuine deletion is filtered upstream). Subscription stays enabled, the next
    scheduled cycle retries. The failure is surfaced via the per-recipient result
    on the SubscriptionDelivery record and a `subscription_delivery_failed` analytics
    event — SLO outcome is owned by the workflow (asset-level errors only) so it
    isn't asserted at this activity boundary."""
    insight = await sync_to_async(Insight.objects.create)(team=team, short_id="dis-noast", name="no_assets")
    subscription = await sync_to_async(create_subscription)(
        team=team,
        insight=insight,
        created_by=user,
        target_type="email",
        target_value="owner@example.com",
        enabled=True,
    )

    env = ActivityEnvironment()

    with (
        patch("ee.tasks.subscriptions.auto_disable.disable_invalid_subscription") as disable_mock,
        patch("posthog.temporal.subscriptions.activities._capture_delivery_failed_event") as capture_mock,
    ):
        # Bogus id ensures `assets` resolves empty.
        result = await env.run(
            deliver_subscription,
            DeliverSubscriptionInputs(
                subscription_id=subscription.id,
                exported_asset_ids=[99_999_999],
                total_insight_count=1,
            ),
        )

    await sync_to_async(subscription.refresh_from_db)()
    # Subscription stays enabled — transient failure, retries can recover.
    assert subscription.enabled is True
    disable_mock.assert_not_called()
    # `subscription_delivery_failed` analytics still fires so existing dashboards see it.
    capture_mock.assert_called_once()
    # Returns cleanly — workflow records the per-recipient failure but SLO outcome
    # stays success; the next scheduled delivery retries.
    assert result is not None
    assert result.recipient_results[0].status == "failed"
    error = result.recipient_results[0].error
    assert error is not None
    assert error["type"] == "no_assets"


@pytest.mark.asyncio
async def test_deliver_subscription_retry_idempotent_after_auto_disable(team, user):
    """Simulates a Temporal redispatch after a successful auto-disable: first call
    auto-disables, second call must observe the entry guard and return without
    re-firing the disable email or analytics. UUID4 campaign keys mean
    MessagingRecord wouldn't dedup the duplicate email otherwise."""
    insight = await sync_to_async(Insight.objects.create)(team=team, short_id="retry-skip", name="retry idempotency")
    asset = await sync_to_async(ExportedAsset.objects.create)(
        team=team, insight=insight, export_format="image/png", content_location="s3://bucket/retry.png"
    )
    # webhook is unsupported, so the first call hits the auto-disable branch.
    subscription = await sync_to_async(create_subscription)(
        team=team,
        insight=insight,
        created_by=user,
        target_type="webhook",
        target_value="https://example.com/hook",
        enabled=True,
    )

    env = ActivityEnvironment()
    inputs = DeliverSubscriptionInputs(
        subscription_id=subscription.id, exported_asset_ids=[asset.id], total_insight_count=1
    )

    # First call: unsupported_target triggers auto-disable + per-recipient failure.
    with (
        patch("ee.tasks.subscriptions.auto_disable.send_notifications_for_disabled_subscription") as send_mock,
        patch("posthog.temporal.subscriptions.activities._capture_delivery_failed_event") as capture_mock,
    ):
        first_result = await env.run(deliver_subscription, inputs)

    assert first_result.recipient_results[0].status == "failed"
    error = first_result.recipient_results[0].error
    assert error is not None
    assert error["type"] == "unsupported_target"
    send_mock.assert_called_once()
    capture_mock.assert_called_once()

    await sync_to_async(subscription.refresh_from_db)()
    assert subscription.enabled is False

    # Second call simulates the Temporal redispatch — the entry guard short-circuits
    # so the disable email and analytics event do NOT fire again.
    with (
        patch("ee.tasks.subscriptions.auto_disable.send_notifications_for_disabled_subscription") as send_mock,
        patch("posthog.temporal.subscriptions.activities._capture_delivery_failed_event") as capture_mock,
    ):
        second_result = await env.run(deliver_subscription, inputs)

    assert second_result.recipient_results == []
    send_mock.assert_not_called()
    capture_mock.assert_not_called()


@pytest.mark.parametrize(
    "label,target_type,target_value,initial_enabled,expected_aborts,expects_failed_recipient,expected_final_enabled",
    [
        ("valid_email_no_abort", "email", "ok@example.com", True, False, False, True),
        ("unsupported_webhook_auto_disables", "webhook", "https://example.com/hook", True, True, True, False),
        ("already_disabled_short_circuits", "email", "dis@example.com", False, True, False, False),
    ],
)
@pytest.mark.asyncio
async def test_validate_subscription_for_delivery(
    team,
    user,
    label,
    target_type,
    target_value,
    initial_enabled,
    expected_aborts,
    expects_failed_recipient,
    expected_final_enabled,
):
    insight = await sync_to_async(Insight.objects.create)(team=team, short_id=f"vld-{label[:5]}", name=label)
    subscription = await sync_to_async(create_subscription)(
        team=team,
        insight=insight,
        created_by=user,
        target_type=target_type,
        target_value=target_value,
        enabled=initial_enabled,
    )

    env = ActivityEnvironment()
    with (
        patch("ee.tasks.subscriptions.auto_disable.send_notifications_for_disabled_subscription") as send_mock,
        patch("posthog.temporal.subscriptions.activities._capture_delivery_failed_event") as capture_mock,
    ):
        abort_info = await env.run(validate_subscription_for_delivery, subscription.id)

    if expected_aborts:
        assert abort_info is not None
        if expects_failed_recipient:
            assert abort_info.failed_recipient is not None
            assert abort_info.failed_recipient.recipient == target_value
            assert abort_info.failed_recipient.status == "failed"
        else:
            assert abort_info.failed_recipient is None
    else:
        assert abort_info is None
    assert send_mock.called is expects_failed_recipient
    assert capture_mock.called is expects_failed_recipient
    await sync_to_async(subscription.refresh_from_db)()
    assert subscription.enabled is expected_final_enabled


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
async def test_create_export_assets_persists_insight_snapshots_to_delivery_content(
    mock_analytics: MagicMock,
    mock_build_snapshot: MagicMock,
    temporal_client: Client,
    team,
    user,
):
    # Insight snapshots are persisted directly to SubscriptionDelivery.content_snapshot
    # from within the activity — they no longer traverse the Temporal payload boundary.
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
    delivery_id = await env.run(
        create_delivery_record,
        CreateDeliveryRecordInputs(
            subscription_id=subscription.id,
            team_id=team.id,
            trigger_type=SubscriptionTriggerType.SCHEDULED,
            temporal_workflow_id="wf-prep-1",
            idempotency_key="idem-prep-1",
        ),
    )
    result = await env.run(
        create_export_assets,
        CreateExportAssetsInputs(subscription_id=subscription.id, delivery_id=delivery_id),
    )

    assert len(result.exported_asset_ids) == 1

    delivery = await sync_to_async(SubscriptionDelivery.objects.get)(pk=delivery_id)
    assert delivery.content_snapshot["total_insight_count"] == 1
    assert len(delivery.content_snapshot["insights"]) == 1
    assert delivery.content_snapshot["insights"][0]["query_hash"] == "cache_key_test"
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
async def test_update_delivery_record_patches_status_and_results_without_touching_content(team, user):
    # When the new workflow calls update_delivery_record without content_snapshot
    # — which is the production path, since create_export_assets owns the
    # snapshot write — the delivery row's existing content_snapshot is preserved.
    # The field still exists on the dataclass for rolling-deploy replay compat
    # (old in-flight workflows may populate it), but it's no longer part of the
    # steady-state call path.
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
    # Snapshot the content written by create_delivery_record so we can assert
    # update_delivery_record does not modify it.
    original_row = await sync_to_async(SubscriptionDelivery.objects.get)(pk=delivery_id)
    initial_content_snapshot = original_row.content_snapshot

    await env.run(
        update_delivery_record,
        UpdateDeliveryRecordInputs(
            delivery_id=delivery_id,
            status=DeliveryStatus.COMPLETED,
            exported_asset_ids=[101, 102],
            recipient_results=[{"recipient": "r@example.com", "status": "success"}],
            error=None,
            finished=True,
        ),
    )

    row = await sync_to_async(SubscriptionDelivery.objects.get)(pk=delivery_id)
    assert row.status == SubscriptionDelivery.Status.COMPLETED
    assert row.exported_asset_ids == [101, 102]
    assert row.recipient_results == [{"recipient": "r@example.com", "status": "success"}]
    assert row.content_snapshot == initial_content_snapshot
    assert row.finished_at is not None


@freeze_time("2022-02-02T08:55:00.000Z")
@pytest.mark.asyncio
async def test_update_delivery_record_merges_content_snapshot_for_legacy_replay(team, user):
    # Rolling-deploy compat path: when a pre-patch workflow replays Phase 2.5
    # on a new worker, it re-issues update_delivery_record with a populated
    # content_snapshot. The activity must shallow-merge so that earlier keys
    # (e.g. dashboard metadata written by create_delivery_record, or insights
    # already written to Postgres by the new create_export_assets activity)
    # are preserved, not overwritten, when the replayed payload only covers a
    # subset of keys.
    insight = await sync_to_async(Insight.objects.create)(team=team, short_id="lgcy01", name="Legacy replay")
    subscription = await sync_to_async(create_subscription)(team=team, insight=insight, created_by=user)

    env = ActivityEnvironment()
    delivery_id = await env.run(
        create_delivery_record,
        CreateDeliveryRecordInputs(
            subscription_id=subscription.id,
            team_id=team.id,
            trigger_type=SubscriptionTriggerType.MANUAL,
            temporal_workflow_id="wf-lgcy",
            idempotency_key="idem-lgcy",
            scheduled_at=None,
        ),
    )

    # Simulate "create_export_assets already wrote insights to DB" — this is
    # the state on a pre-patch workflow retry where the new activity persisted
    # the snapshot before the workflow reaches the legacy Phase 2.5 replay.
    await sync_to_async(
        SubscriptionDelivery.objects.filter(pk=delivery_id).update,
    )(content_snapshot={"id": 1, "short_id": "abc", "insights": [{"id": 99, "name": "inline-write"}]})

    # Legacy replay with insights set should overwrite the insights key but
    # preserve id/short_id set by create_delivery_record.
    await env.run(
        update_delivery_record,
        UpdateDeliveryRecordInputs(
            delivery_id=delivery_id,
            status=DeliveryStatus.STARTING,
            content_snapshot={
                "total_insight_count": 1,
                "insights": [{"id": 99, "name": "replayed-insights"}],
            },
        ),
    )

    row = await sync_to_async(SubscriptionDelivery.objects.get)(pk=delivery_id)
    # Top-level merge preserved id/short_id from the pre-existing content_snapshot.
    assert row.content_snapshot["id"] == 1
    assert row.content_snapshot["short_id"] == "abc"
    # Replay's keys took precedence for the keys it included.
    assert row.content_snapshot["total_insight_count"] == 1
    assert row.content_snapshot["insights"] == [{"id": 99, "name": "replayed-insights"}]

    # Legacy replay without the `insights` key (new activity returned
    # insight_snapshots=None) must NOT wipe the insights already persisted by
    # the new activity.
    await env.run(
        update_delivery_record,
        UpdateDeliveryRecordInputs(
            delivery_id=delivery_id,
            status=DeliveryStatus.STARTING,
            content_snapshot={"total_insight_count": 2},  # no insights key
        ),
    )

    row = await sync_to_async(SubscriptionDelivery.objects.get)(pk=delivery_id)
    # insights from the previous replay are preserved.
    assert row.content_snapshot["insights"] == [{"id": 99, "name": "replayed-insights"}]
    # total_insight_count was updated.
    assert row.content_snapshot["total_insight_count"] == 2


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


def test_create_export_assets_result_fields_stable_reminder():
    # Reminder-style guard: fails if a field is added to CreateExportAssetsResult
    # without the author noticing. Temporal activity payloads are capped at
    # ~2 MiB (TMPRL1103), so any new field must be size-bounded by construction
    # — primitives, IDs, short strings, or small lists of primitives. Multi-MB
    # data must be persisted from inside the activity (e.g. SubscriptionDelivery
    # .content_snapshot via Postgres), not returned.
    #
    # Only the field name set is checked here — the test can't catch field
    # *type* bloat (e.g. someone changing `target_type: str` to
    # `target_type: dict[str, Any]`). That risk is caught at review time by the
    # AGENTS.md rule on activity payload size.
    small_metadata_fields = {
        "exported_asset_ids",
        "total_insight_count",
        "team_id",
        "distinct_id",
        "target_type",
    }
    # Kept on the dataclass for rolling-deploy replay compatibility. New code
    # does not populate them. Remove from this set when the fields are removed
    # from types.py (after the subscriptions task queue has drained).
    deprecated_fields = {"insight_snapshots"}
    expected_fields = small_metadata_fields | deprecated_fields
    actual_fields = {f.name for f in dataclasses.fields(CreateExportAssetsResult)}
    assert actual_fields == expected_fields, (
        f"CreateExportAssetsResult fields changed: added={actual_fields - expected_fields}, "
        f"removed={expected_fields - actual_fields}. If adding a field, confirm it is "
        f"size-bounded — Temporal activity payloads are capped at ~2 MiB (TMPRL1103). "
        f"Persist multi-MB data from within the activity rather than returning it."
    )

    # Byte-ceiling sanity check: an empty result instance with default values
    # stays well under any plausible payload concern. Catches accidental large
    # defaults on new fields (e.g. a mutable default factory that pulls data).
    empty = CreateExportAssetsResult(exported_asset_ids=[], total_insight_count=0)

    encoded_size = len(json.dumps(dataclasses.asdict(empty), default=str).encode("utf-8"))
    assert encoded_size < 1024, (
        f"Empty CreateExportAssetsResult serialized to {encoded_size} bytes — larger than expected. "
        f"New fields should not carry non-trivial default values."
    )


@patch("posthog.temporal.exports.activities.exporter")
@patch("posthog.slo.events.posthoganalytics")
@patch("ee.tasks.subscriptions.get_metric_meter")
@patch("posthog.temporal.subscriptions.activities.send_email_subscription_report")
@patch("posthog.temporal.subscriptions.activities.build_insight_delivery_snapshot")
@pytest.mark.asyncio
async def test_workflow_survives_large_insight_snapshot(
    mock_build_snapshot: MagicMock,
    mock_send_email: MagicMock,
    mock_metric_meter: MagicMock,
    mock_analytics: MagicMock,
    mock_exporter: MagicMock,
    temporal_client: Client,
    subscriptions_worker,
    team,
    user,
):
    # Regression test for Temporal payload size limit (TMPRL1103, ~2 MiB).
    # A raw HogQL query with `LIMIT 50000` over 7 narrow columns produces ~4.4 MB
    # of serialized query results. If those results are shuttled through an activity
    # return value, the workflow fails before emails are ever dispatched.
    insight = await sync_to_async(Insight.objects.create)(team=team, short_id="bigrpt", name="Large Report")

    subscription = await sync_to_async(create_subscription)(
        team=team,
        insight=insight,
        created_by=user,
        target_value="test@posthog.com",
    )

    # Mirror the production repro: 50k rows of 7 short column values. Each row
    # serializes to ~85-90 bytes, yielding a ~4 MB payload — about 2x Temporal's limit.
    rows = [["01-Apr-26", "google", "cpc", "campaign-slug-1234", "TXN1234567", 1, 12.34] for _ in range(50_000)]
    mock_build_snapshot.return_value = {
        "id": insight.id,
        "short_id": insight.short_id,
        "name": insight.name,
        "query_hash": "fake_hash",
        "cache_key": "fake_cache_key",
        "comparison_enabled": False,
        "query_results": {
            "columns": ["Date", "source", "medium", "campaign", "transactionID", "Orders", "Revenue"],
            "results": rows,
        },
    }

    def fake_export(asset_obj, **kwargs):
        asset_obj.content_location = "s3://bucket/big.png"
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
                    trigger_type=SubscriptionTriggerType.MANUAL,
                ),
                id=str(uuid.uuid4()),
                task_queue=settings.TEMPORAL_TASK_QUEUE,
            )

    # Workflow must complete end-to-end despite the ~4 MB snapshot.
    assert mock_send_email.call_count == 1

    def _fetch_deliveries() -> list[SubscriptionDelivery]:
        return list(SubscriptionDelivery.objects.filter(subscription=subscription).order_by("-created_at"))

    deliveries = await sync_to_async(_fetch_deliveries)()
    assert len(deliveries) == 1
    assert deliveries[0].status == DeliveryStatus.COMPLETED

    # Content snapshot must be persisted with full fidelity — the whole point of the
    # SubscriptionDelivery history feature. Postgres JSONB has no 2 MiB ceiling.
    content = deliveries[0].content_snapshot
    assert "insights" in content
    assert len(content["insights"]) == 1
    assert len(content["insights"][0]["query_results"]["results"]) == 50_000


async def test_fetch_due_subscriptions_excludes_disabled(team, user):
    dashboard = await sync_to_async(Dashboard.objects.create)(team=team, name="dashboard", created_by=user)

    now = datetime.now(tz=ZoneInfo("UTC"))

    enabled_sub = await sync_to_async(Subscription.objects.create)(
        team=team,
        dashboard=dashboard,
        title="enabled sub",
        target_type="email",
        target_value="vasco@posthog.com",
        frequency="daily",
        start_date=now,
        enabled=True,
    )
    disabled_sub = await sync_to_async(Subscription.objects.create)(
        team=team,
        dashboard=dashboard,
        title="disabled sub",
        target_type="email",
        target_value="vasco@posthog.com",
        frequency="daily",
        start_date=now,
        enabled=False,
    )

    # The model's save() advances next_delivery_date to the future via rrule.
    # Force both subs into the "due" window so the buffer alone doesn't filter them out.
    await sync_to_async(Subscription.objects.filter(id__in=[enabled_sub.id, disabled_sub.id]).update)(
        next_delivery_date=now,
    )

    env = ActivityEnvironment()
    result = await env.run(
        fetch_due_subscriptions_activity,
        FetchDueSubscriptionsActivityInputs(buffer_minutes=15),
    )
    fetched_ids = {sub.subscription_id for sub in result}

    assert enabled_sub.id in fetched_ids
    assert disabled_sub.id not in fetched_ids


@patch("ee.tasks.subscriptions.auto_disable.send_notifications_for_disabled_subscription")
@patch("posthog.temporal.subscriptions.activities.build_insight_delivery_snapshot")
@patch("posthog.temporal.subscriptions.activities.get_slack_integration_for_team", return_value=None)
@patch("posthog.temporal.exports.activities.exporter")
@patch("posthog.slo.events.posthoganalytics")
@freeze_time("2022-02-02T08:55:00.000Z")
@pytest.mark.asyncio
async def test_deliver_subscription_emits_success_slo_when_disabling(
    mock_slo_analytics: MagicMock,
    mock_exporter: MagicMock,
    mock_get_slack: MagicMock,
    mock_build_snapshot: MagicMock,
    mock_send_notification: MagicMock,
    temporal_client: Client,
    team,
    user,
):
    # The slack-missing-integration branch auto-disables and returns cleanly, so
    # the SLO interceptor records outcome=success. Locks in as a regression invariant.
    insight = await sync_to_async(Insight.objects.create)(team=team, short_id="slo-d1", name="SLO disable")
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
        content_location="s3://bucket/slo-disable.png",
    )

    # Stub out the actual export — the test insight has no series, so the
    # real exporter would raise ValidationError and pollute the SLO outcome
    # with PartialExportFailure before deliver_subscription even runs.
    def fake_export(asset_obj, **kwargs):
        asset_obj.content_location = "s3://bucket/slo-disable.png"
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

    # Sanity: auto-disable wired correctly.
    await sync_to_async(subscription.refresh_from_db)()
    assert subscription.enabled is False
    mock_send_notification.assert_called_once()

    delivery_completed_calls = [
        c
        for c in mock_slo_analytics.capture.call_args_list
        if c.kwargs.get("event") == "slo_operation_completed"
        and c.kwargs.get("properties", {}).get("operation") == SloOperation.SUBSCRIPTION_DELIVERY
    ]
    # At least one subscription_delivery completion was recorded.
    assert delivery_completed_calls, "expected an slo_operation_completed event for subscription_delivery"

    for call in delivery_completed_calls:
        props = call.kwargs["properties"]
        assert props["outcome"] == SloOutcome.SUCCESS, (
            f"subscription_delivery SLO must stay success after auto-disable, got {props}"
        )
