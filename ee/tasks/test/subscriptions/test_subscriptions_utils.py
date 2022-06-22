from typing import List
from unittest.mock import MagicMock, patch

import pytest

from ee.tasks.subscriptions.subscription_utils import (
    DEFAULT_MAX_ASSET_COUNT,
    generate_assets,
    get_tiles_ordered_by_position,
)
from ee.tasks.test.subscriptions.utils_subscription_tests import create_subscription
from posthog.models.dashboard import Dashboard
from posthog.models.dashboard_tile import DashboardTile
from posthog.models.exported_asset import ExportedAsset
from posthog.models.insight import Insight
from posthog.test.base import APIBaseTest
from posthog.test.db_context_capturing import capture_db_queries


@patch("ee.tasks.subscriptions.subscription_utils.group")
@patch("ee.tasks.subscriptions.subscription_utils.export_task")
class TestSubscriptionsTasksUtils(APIBaseTest):
    dashboard: Dashboard
    insight: Insight
    asset: ExportedAsset
    tiles: List[DashboardTile]

    def setUp(self) -> None:
        self.dashboard = Dashboard.objects.create(team=self.team, name="private dashboard", created_by=self.user)
        self.insight = Insight.objects.create(team=self.team, short_id="123456", name="My Test subscription")
        self.tiles = []
        for _ in range(10):
            self.tiles.append(DashboardTile.objects.create(dashboard=self.dashboard, insight=self.insight))

        self.subscription = create_subscription(team=self.team, insight=self.insight, created_by=self.user)

    def test_loads_dashboard_tiles_efficiently(self, mock_export_task: MagicMock, mock_group: MagicMock) -> None:
        with capture_db_queries() as capture_query_context:
            tiles = get_tiles_ordered_by_position(dashboard=self.dashboard)

            for tile in tiles:
                assert tile.insight.id

            assert len(tiles) == 10

        assert len(capture_query_context.captured_queries) == 1

    def test_generate_assets_for_insight(self, mock_export_task: MagicMock, mock_group: MagicMock) -> None:
        insights, assets = generate_assets(self.subscription)

        assert insights == [self.insight]
        assert len(assets) == 1
        assert mock_export_task.s.call_count == 1

    def test_generate_assets_for_dashboard(self, mock_export_task: MagicMock, mock_group: MagicMock) -> None:
        subscription = create_subscription(team=self.team, dashboard=self.dashboard, created_by=self.user)

        insights, assets = generate_assets(subscription)

        assert len(insights) == len(self.tiles)
        assert len(assets) == DEFAULT_MAX_ASSET_COUNT
        assert mock_export_task.s.call_count == DEFAULT_MAX_ASSET_COUNT

    def test_raises_if_missing_resource(self, mock_export_task: MagicMock, mock_group: MagicMock) -> None:
        subscription = create_subscription(team=self.team, created_by=self.user)

        with pytest.raises(Exception) as e:
            generate_assets(subscription)

        assert str(e.value) == "There are no insights to be sent for this Subscription"
