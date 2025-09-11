import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from posthog.models.dashboard import Dashboard
from posthog.models.dashboard_tile import DashboardTile
from posthog.models.exported_asset import ExportedAsset
from posthog.models.insight import Insight

from ee.tasks.subscriptions.subscription_utils import DEFAULT_MAX_ASSET_COUNT, generate_assets
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
