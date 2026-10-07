import datetime

from posthog.test.base import APIBaseTest

from django.core.exceptions import ValidationError
from django.db.utils import IntegrityError

from parameterized import parameterized

from posthog.models import Team

from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.models.dashboard_tile import ButtonTile, DashboardTile, Text
from products.exports.backend.models.exported_asset import ExportedAsset
from products.product_analytics.backend.facade.models import Insight


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

    def test_save_auto_derives_team_id_from_dashboard(self) -> None:
        insight = Insight.objects.create(team=self.team, short_id="autoderive", name="autoderive")
        tile = DashboardTile(dashboard=self.dashboard, insight=insight)
        # team is unset before save
        self.assertIsNone(tile.team_id)
        tile.save()
        # save() copies dashboard.team_id onto the tile so HogQL queries scoped
        # by `WHERE team_id = X` find this row.
        self.assertEqual(tile.team_id, self.dashboard.team_id)

    def test_save_does_not_overwrite_explicit_team_id(self) -> None:
        insight = Insight.objects.create(team=self.team, short_id="explicit", name="explicit")
        tile = DashboardTile(dashboard=self.dashboard, insight=insight, team_id=self.team.id)
        tile.save()
        self.assertEqual(tile.team_id, self.team.id)

    @parameterized.expand([("text",), ("button_tile",)])
    def test_copy_uses_current_content_after_reference_changes(self, content_field: str) -> None:
        if content_field == "text":
            original: Text | ButtonTile = Text.objects.create(team=self.team, body="Original")
            updated: Text | ButtonTile = Text.objects.create(
                team=self.team,
                body="Updated",
                agent_context="Context",
                created_by=self.user,
                last_modified_by=self.user,
            )
        else:
            original = ButtonTile.objects.create(team=self.team, url="https://example.com/original", text="Original")
            updated = ButtonTile.objects.create(
                team=self.team,
                url="https://example.com/updated",
                text="Updated",
                placement="right",
                style="secondary",
                created_by=self.user,
                last_modified_by=self.user,
            )
        source = DashboardTile.objects.create(dashboard=self.dashboard, **{content_field: original})
        source = DashboardTile.objects.select_related(content_field).get(pk=source.pk)
        DashboardTile.objects.filter(pk=source.pk).update(**{content_field: updated})
        destination_team = Team.objects.create(organization=self.organization, project=self.project)
        destination = Dashboard.objects.create(team=destination_team, name="Destination")

        source.copy_to_dashboard(destination)

        copied = DashboardTile.objects.get(dashboard=destination)
        if content_field == "text":
            assert copied.text is not None
            assert copied.text.body == "Updated"
            assert copied.text.agent_context == "Context"
            copied_content: Text | ButtonTile = copied.text
        else:
            assert copied.button_tile is not None
            assert copied.button_tile.url == "https://example.com/updated"
            assert copied.button_tile.placement == "right"
            assert copied.button_tile.style == "secondary"
            copied_content = copied.button_tile
        assert copied_content.id != updated.id
        assert copied_content.team_id == destination_team.id
        assert copied_content.created_by_id == updated.created_by_id
        assert copied_content.last_modified_at == updated.last_modified_at
        assert copied_content.last_modified_by_id == updated.last_modified_by_id
