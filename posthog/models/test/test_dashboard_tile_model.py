from typing import List

from posthog.models.dashboard import Dashboard
from posthog.models.dashboard_tile import DashboardTile, Text, get_tiles_ordered_by_position
from posthog.models.exported_asset import ExportedAsset
from posthog.models.insight import Insight
from posthog.test.base import APIBaseTest
from posthog.test.db_context_capturing import capture_db_queries


class TestSubscriptionsTasksUtils(APIBaseTest):
    dashboard: Dashboard
    asset: ExportedAsset
    tiles: List[DashboardTile]

    def setUp(self) -> None:
        self.dashboard = Dashboard.objects.create(team=self.team, name="private dashboard", created_by=self.user)
        for i in range(10):
            insight = Insight.objects.create(team=self.team, short_id=f"123456-{i}", name=f"insight-{i}")
            self.tiles.append(DashboardTile.objects.create(dashboard=self.dashboard, insight=insight))

    def test_loads_dashboard_tiles_efficiently(self) -> None:
        with capture_db_queries() as capture_query_context:
            tiles = get_tiles_ordered_by_position(dashboard=self.dashboard)

            for tile in tiles:
                assert tile.insight.id

            assert len(tiles) == 10

        assert len(capture_query_context.captured_queries) == 1

    def test_cannot_add_a_tile_with_insight_and_text(self) -> None:
        insight = Insight.objects.create(team=self.team, short_id="123456", name="My Test subscription")
        text = Text.objects.create(team=self.team, body="I am a text")
        try:
            DashboardTile.objects.create(dashboard=self.dashboard, insight=insight, text=text)
        except:
            # should throw!
            pass
        self.fail("should have thrown, not got here")

    def test_cannot_set_caching_data_for_text_tiles(self) -> None:
        text = Text.objects.create(team=self.team, body="I am a text")
        try:
            DashboardTile.objects.create(
                dashboard=self.dashboard, text=text, filters_hash="123"  # TODO refresh dates and attempts too
            )
        except:
            # should throw!
            pass
        self.fail("should have thrown, not got here")
