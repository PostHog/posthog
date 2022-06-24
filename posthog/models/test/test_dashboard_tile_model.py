from typing import List

from posthog.models.dashboard import Dashboard
from posthog.models.dashboard_tile import DashboardTile, get_tiles_ordered_by_position
from posthog.models.exported_asset import ExportedAsset
from posthog.models.insight import Insight
from posthog.test.base import APIBaseTest
from posthog.test.db_context_capturing import capture_db_queries


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

    def test_loads_dashboard_tiles_efficiently(self) -> None:
        with capture_db_queries() as capture_query_context:
            tiles = get_tiles_ordered_by_position(dashboard=self.dashboard)

            for tile in tiles:
                assert tile.insight.id

            assert len(tiles) == 10

        assert len(capture_query_context.captured_queries) == 1
