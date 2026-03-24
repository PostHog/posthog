import datetime

from posthog.test.base import APIBaseTest

from django.core.exceptions import ValidationError
from django.db.utils import IntegrityError

from posthog.models.dashboard import Dashboard
from posthog.models.dashboard_tile import DashboardTile, Text
from posthog.models.exported_asset import ExportedAsset
from posthog.models.insight import Insight


class TestDashboardTileModel(APIBaseTest):
    dashboard: Dashboard
    asset: ExportedAsset
    tiles: list[DashboardTile]

    def setUp(self) -> None:
        self.dashboard = Dashboard.objects.create(team=self.team, name="private dashboard", created_by=self.user)
        for i in range(10):
            if i > 6:
                text = Text.objects.create(team=self.team, body=f"text-{i}")
                DashboardTile.objects.create(dashboard=self.dashboard, text=text)
            else:
                insight = Insight.objects.create(team=self.team, short_id=f"123456-{i}", name=f"insight-{i}")
                DashboardTile.objects.create(dashboard=self.dashboard, insight=insight)

    def test_cannot_add_a_tile_with_insight_and_text_on_validation(self) -> None:
        insight = Insight.objects.create(team=self.team, short_id="123456", name="My Test subscription")
        text = Text.objects.create(team=self.team, body="I am a text")

        with self.assertRaises(IntegrityError):
            DashboardTile.objects.create(dashboard=self.dashboard, insight=insight, text=text)

    def test_cannot_set_caching_data_for_text_tiles(self) -> None:
        tile_fields: list[dict] = [
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

    def test_sort_tiles_by_layout_tiebreaks_by_pk_when_positions_match(self) -> None:
        """Same (y, x) must sort deterministically so duplicate tiles never flap before the original."""
        dashboard = Dashboard.objects.create(team=self.team, name="sort tiebreak", created_by=self.user)
        insight_a = Insight.objects.create(team=self.team, short_id="aaaaaa", name="a")
        insight_b = Insight.objects.create(team=self.team, short_id="bbbbbb", name="b")
        same_sm = {"sm": {"x": 0, "y": 0, "w": 6, "h": 5}}
        tile_lower_pk = DashboardTile.objects.create(dashboard=dashboard, insight=insight_a, layouts=same_sm)
        tile_higher_pk = DashboardTile.objects.create(dashboard=dashboard, insight=insight_b, layouts=same_sm)
        assert tile_lower_pk.pk < tile_higher_pk.pk

        sorted_tiles = DashboardTile.sort_tiles_by_layout([tile_higher_pk, tile_lower_pk], "sm")
        assert sorted_tiles == [tile_lower_pk, tile_higher_pk]
