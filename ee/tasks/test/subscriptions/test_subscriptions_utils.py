import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from posthog.models.dashboard import Dashboard
from posthog.models.dashboard_tile import DashboardTile
from posthog.models.exported_asset import ExportedAsset
from posthog.models.insight import Insight

from ee.tasks.subscriptions.subscription_utils import DEFAULT_MAX_ASSET_COUNT, generate_assets, generate_assets_async
from ee.tasks.test.subscriptions.subscriptions_test_factory import create_subscription


@patch("ee.tasks.subscriptions.subscription_utils.chain")
@patch("ee.tasks.subscriptions.subscription_utils.exporter.export_asset")
class TestSubscriptionsTasksUtils(APIBaseTest):
    dashboard: Dashboard
    insight: Insight
    asset: ExportedAsset
    tiles: list[DashboardTile]

    def setUp(self) -> None:
        self.dashboard = Dashboard.objects.create(team=self.team, name="private dashboard", created_by=self.user)
        self.insight = Insight.objects.create(team=self.team, short_id="123456", name="My Test subscription")
        self.tiles = []
        for i in range(10):
            insight = Insight.objects.create(team=self.team, short_id=f"insight-{i}", name="My Test subscription")
            self.tiles.append(DashboardTile.objects.create(dashboard=self.dashboard, insight=insight))

        self.subscription = create_subscription(team=self.team, insight=self.insight, created_by=self.user)

    def test_generate_assets_for_insight(self, mock_export_task: MagicMock, _mock_group: MagicMock) -> None:
        with self.settings(PARALLEL_ASSET_GENERATION_MAX_TIMEOUT_MINUTES=1):
            insights, assets = generate_assets(self.subscription)

            assert insights == [self.insight]
            assert len(assets) == 1
            assert mock_export_task.si.call_count == 1

    def test_generate_assets_for_dashboard(self, mock_export_task: MagicMock, _mock_group: MagicMock) -> None:
        subscription = create_subscription(team=self.team, dashboard=self.dashboard, created_by=self.user)

        with self.settings(PARALLEL_ASSET_GENERATION_MAX_TIMEOUT_MINUTES=1):
            insights, assets = generate_assets(subscription)

        assert len(insights) == len(self.tiles)
        assert len(assets) == DEFAULT_MAX_ASSET_COUNT
        assert mock_export_task.si.call_count == DEFAULT_MAX_ASSET_COUNT

    def test_raises_if_missing_resource(self, _mock_export_task: MagicMock, _mock_group: MagicMock) -> None:
        subscription = create_subscription(team=self.team, created_by=self.user)

        with self.settings(PARALLEL_ASSET_GENERATION_MAX_TIMEOUT_MINUTES=1), pytest.raises(Exception) as e:
            generate_assets(subscription)

        assert str(e.value) == "There are no insights to be sent for this Subscription"

    def test_excludes_deleted_insights_for_dashboard(self, mock_export_task: MagicMock, _mock_group: MagicMock) -> None:
        for i in range(1, 10):
            current_tile = self.tiles[i]
            if current_tile.insight is None:
                continue
            current_tile.insight.deleted = True
            current_tile.insight.save()
        subscription = create_subscription(team=self.team, dashboard=self.dashboard, created_by=self.user)

        with self.settings(PARALLEL_ASSET_GENERATION_MAX_TIMEOUT_MINUTES=1):
            insights, assets = generate_assets(subscription)

            assert len(insights) == 1
            assert len(assets) == 1
            assert mock_export_task.si.call_count == 1

    def test_cancels_children_if_timed_out(self, _mock_export_task: MagicMock, mock_group: MagicMock) -> None:
        # mock the group so that its children are never ready,
        # and we capture calls to revoke
        mock_running_exports = MagicMock()
        mock_ready = MagicMock()
        running_export_task = MagicMock()

        running_export_task.state = "PENDING"

        mock_ready.return_value = False
        mock_group.return_value.apply_async.return_value = mock_running_exports

        mock_running_exports.children = [running_export_task]
        mock_running_exports.ready = mock_ready

        with self.settings(PARALLEL_ASSET_GENERATION_MAX_TIMEOUT_MINUTES=0.01), pytest.raises(Exception) as e:
            generate_assets(self.subscription)

        assert str(e.value) == "Timed out waiting for celery task to finish"
        running_export_task.revoke.assert_called()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
@patch("ee.tasks.subscriptions.subscription_utils.exporter.export_asset_direct")
async def test_async_generate_assets_basic(mock_export: MagicMock, team, user) -> None:
    from asgiref.sync import sync_to_async

    def export_success(asset: ExportedAsset) -> None:
        asset.content = b"fake image data"
        asset.save()

    mock_export.side_effect = export_success

    # Create test data
    dashboard = await sync_to_async(Dashboard.objects.create)(team=team, name="test dashboard", created_by=user)

    for i in range(3):
        insight = await sync_to_async(Insight.objects.create)(team=team, short_id=f"insight-{i}", name=f"Insight {i}")
        await sync_to_async(DashboardTile.objects.create)(dashboard=dashboard, insight=insight)

    subscription = await sync_to_async(create_subscription)(team=team, dashboard=dashboard, created_by=user)

    # Fetch with prefetched relationships
    subscription = await sync_to_async(
        lambda: type(subscription)
        .objects.select_related("team", "dashboard", "insight", "created_by")
        .get(id=subscription.id)
    )()

    insights, assets = await generate_assets_async(subscription)

    assert len(insights) == 3
    assert len(assets) == 3
    assert mock_export.call_count == 3
    assert all(asset.content for asset in assets)


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
@patch("ee.tasks.subscriptions.subscription_utils.asyncio.wait_for")
@patch("posthog.tasks.exporter.export_asset_direct")
async def test_async_generate_assets_timeout_continues_with_partial_results(
    mock_export: MagicMock, mock_wait_for: MagicMock, team, user
) -> None:
    from asgiref.sync import sync_to_async

    mock_export.return_value = None
    # Mock wait_for to immediately raise TimeoutError
    mock_wait_for.side_effect = TimeoutError()

    # Create test data
    dashboard = await sync_to_async(Dashboard.objects.create)(team=team, name="test dashboard", created_by=user)

    for i in range(3):
        insight = await sync_to_async(Insight.objects.create)(team=team, short_id=f"insight-{i}", name=f"Insight {i}")
        await sync_to_async(DashboardTile.objects.create)(dashboard=dashboard, insight=insight)

    subscription = await sync_to_async(create_subscription)(team=team, dashboard=dashboard, created_by=user)

    # Fetch subscription with prefetched relationships
    subscription = await sync_to_async(
        lambda: type(subscription)
        .objects.select_related("team", "dashboard", "insight", "created_by")
        .get(id=subscription.id)
    )()

    insights, assets = await generate_assets_async(subscription)

    # Should return insights even though exports timed out
    assert len(insights) == 3
    # Should return all assets even though none have content
    assert len(assets) == 3
    # Assets won't have content or content_location since timeout happened immediately
    assert all(asset.content is None and asset.content_location is None for asset in assets)
    # Verify timeout was triggered
    assert mock_wait_for.called


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
@patch("posthog.tasks.exporter.export_asset_direct")
async def test_async_generate_assets_partial_success(mock_export: MagicMock, team, user) -> None:
    from asgiref.sync import sync_to_async

    call_count = 0

    def export_with_partial_success(asset: ExportedAsset) -> None:
        nonlocal call_count
        call_count += 1
        # First 2 assets succeed, third fails
        if call_count <= 2:
            asset.content = b"fake image data"
            asset.save()

    mock_export.side_effect = export_with_partial_success

    # Create test data
    dashboard = await sync_to_async(Dashboard.objects.create)(team=team, name="test dashboard", created_by=user)

    for i in range(3):
        insight = await sync_to_async(Insight.objects.create)(team=team, short_id=f"insight-{i}", name=f"Insight {i}")
        await sync_to_async(DashboardTile.objects.create)(dashboard=dashboard, insight=insight)

    subscription = await sync_to_async(create_subscription)(team=team, dashboard=dashboard, created_by=user)

    subscription = await sync_to_async(
        lambda: type(subscription)
        .objects.select_related("team", "dashboard", "insight", "created_by")
        .get(id=subscription.id)
    )()

    insights, assets = await generate_assets_async(subscription)

    assert len(insights) == 3
    # All 3 assets returned (not filtered), but only 2 have content
    assert len(assets) == 3
    assets_with_content = [a for a in assets if a.content or a.content_location]
    assets_without_content = [a for a in assets if not a.content and not a.content_location]
    assert len(assets_with_content) == 2
    assert len(assets_without_content) == 1
