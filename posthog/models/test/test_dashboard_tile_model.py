import datetime
from typing import Dict, List

from django.core.exceptions import ValidationError
from django.db.utils import IntegrityError

from posthog.models.dashboard import Dashboard
from posthog.models.dashboard_tile import (
    DashboardTile,
    Text,
    get_tiles_ordered_by_position,
)
from posthog.models.exported_asset import ExportedAsset
from posthog.models.insight import Insight
from posthog.test.base import APIBaseTest
from posthog.test.db_context_capturing import capture_db_queries


class TestDashboardTileModel(APIBaseTest):
    dashboard: Dashboard
    asset: ExportedAsset
    tiles: List[DashboardTile]

    def setUp(self) -> None:
        self.dashboard = Dashboard.objects.create(team=self.team, name="private dashboard", created_by=self.user)
        for i in range(10):
            if i > 6:
                text = Text.objects.create(team=self.team, body=f"text-{i}")
                DashboardTile.objects.create(dashboard=self.dashboard, text=text)
            else:
                insight = Insight.objects.create(team=self.team, short_id=f"123456-{i}", name=f"insight-{i}")
                DashboardTile.objects.create(dashboard=self.dashboard, insight=insight)

    def test_loads_dashboard_tiles_efficiently(self) -> None:
        with capture_db_queries() as capture_query_context:
            tiles = get_tiles_ordered_by_position(dashboard=self.dashboard)

            for tile in tiles:
                assert tile.insight or tile.text

            assert len(tiles) == 10

        assert len(capture_query_context.captured_queries) == 1

    def test_loads_dashboard_tiles_excludes_deleted(self) -> None:
        tiles = get_tiles_ordered_by_position(dashboard=self.dashboard)
        assert len(tiles) == 10

        tiles[0].deleted = True
        tiles[0].save()

        insight = Insight.objects.get(team=self.team, short_id="123456-1")
        insight.deleted = True
        insight.save()

        tiles = get_tiles_ordered_by_position(dashboard=self.dashboard)
        assert len(tiles) == 8

    def test_cannot_add_a_tile_with_insight_and_text_on_validation(self) -> None:
        insight = Insight.objects.create(team=self.team, short_id="123456", name="My Test subscription")
        text = Text.objects.create(team=self.team, body="I am a text")

        with self.assertRaises(IntegrityError):
            DashboardTile.objects.create(dashboard=self.dashboard, insight=insight, text=text)

    def test_cannot_set_caching_data_for_text_tiles(self) -> None:
        tile_fields: List[Dict] = [
            {"filters_hash": "123"},
            {"refreshing": True},
            {"refresh_attempt": 2},
            {"last_refresh": datetime.datetime.now()},
        ]
        for invalid_text_tile_field in tile_fields:
            with self.subTest(option=invalid_text_tile_field):
                with self.assertRaises(ValidationError):
                    text = Text.objects.create(team=self.team, body="I am a text")
                    tile = DashboardTile.objects.create(dashboard=self.dashboard, text=text, **invalid_text_tile_field)
                    tile.clean()
