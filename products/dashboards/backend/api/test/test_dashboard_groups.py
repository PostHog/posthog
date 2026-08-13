from posthog.test.base import APIBaseTest

from rest_framework import status

from posthog.api.test.dashboards import DashboardAPI
from posthog.helpers.dashboard_templates import create_from_template

from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.models.dashboard_group import DashboardGroup
from products.dashboards.backend.models.dashboard_templates import DashboardTemplate
from products.dashboards.backend.models.dashboard_tile import DashboardTile


class TestDashboardGroups(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.dashboard_api = DashboardAPI(self.client, self.team, self.assertEqual)
        self.dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "Grouped dashboard"})

    def _create_group(self, name: str | None, position: int | None = None) -> dict:
        payload: dict = {"name": name}
        if position is not None:
            payload["position"] = position
        response = self.client.post(
            f"/api/projects/{self.team.id}/dashboards/{self.dashboard_id}/groups/",
            payload,
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        return response.json()

    def test_first_group_wraps_existing_tiles_in_anonymous_section(self) -> None:
        _, dashboard = self.dashboard_api.create_text_tile(self.dashboard_id, text="Signups")
        tile_id = dashboard["tiles"][0]["id"]

        named_group = self._create_group("Acquisition")

        groups = list(DashboardGroup.all_teams.filter(dashboard_id=self.dashboard_id).order_by("position"))
        self.assertEqual([(group.name, group.position) for group in groups], [(None, 0), ("Acquisition", 1)])
        self.assertEqual(DashboardTile.objects.get(id=tile_id).parent_group_id, groups[0].id)
        self.assertNotIn("tile_id", named_group)
        self.assertNotIn("layouts", named_group)

    def test_new_tile_appends_to_trailing_anonymous_section(self) -> None:
        self._create_group("Named")
        _, dashboard = self.dashboard_api.create_text_tile(self.dashboard_id, text="Signups")
        tile = DashboardTile.objects.get(id=dashboard["tiles"][0]["id"])

        groups = list(DashboardGroup.all_teams.filter(dashboard_id=self.dashboard_id).order_by("position"))
        self.assertEqual([group.name for group in groups], ["Named", None])
        self.assertEqual(tile.parent_group_id, groups[1].id)

    def test_move_creates_and_removes_anonymous_sections(self) -> None:
        source_group = self._create_group(None)
        _, dashboard = self.dashboard_api.create_text_tile(self.dashboard_id, text="Signups")
        tile_id = dashboard["tiles"][0]["id"]
        tile = DashboardTile.objects.get(id=tile_id)
        self.assertEqual(str(tile.parent_group_id), source_group["id"], "tile should start in the source section")

        response = self.client.post(
            f"/api/projects/{self.team.id}/dashboards/{self.dashboard_id}/groups/move-tile/",
            {"tile_id": tile_id, "create_at_position": 0},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = response.json()
        self.assertEqual(payload["tile"]["parent_group_id"], payload["created_group"]["id"])
        self.assertEqual(payload["deleted_group_ids"], [source_group["id"]])
        self.assertEqual(
            list(DashboardGroup.all_teams.filter(dashboard_id=self.dashboard_id).values_list("position", flat=True)),
            [0],
        )

    def test_group_position_reorder_renumbers_sections(self) -> None:
        first = self._create_group("First")
        second = self._create_group("Second")

        response = self.client.patch(
            f"/api/projects/{self.team.id}/dashboards/{self.dashboard_id}/groups/update/",
            {"group_id": second["id"], "position": 0},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            [
                (str(group_id), position)
                for group_id, position in DashboardGroup.all_teams.filter(dashboard_id=self.dashboard_id)
                .order_by("position")
                .values_list("id", "position")
            ],
            [(second["id"], 0), (first["id"], 1)],
        )

    def test_ungroup_keeps_tiles_and_converts_section_to_anonymous(self) -> None:
        group = self._create_group("Acquisition")
        _, dashboard = self.dashboard_api.create_text_tile(self.dashboard_id, text="Signups")
        tile_id = dashboard["tiles"][0]["id"]
        self.client.post(
            f"/api/projects/{self.team.id}/dashboards/{self.dashboard_id}/groups/move-tile/",
            {"tile_id": tile_id, "group_id": group["id"]},
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/dashboards/{self.dashboard_id}/groups/delete/",
            {"group_id": group["id"], "member_handling": "ungroup"},
        )

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertIsNone(DashboardGroup.all_teams.get(id=group["id"]).name)
        self.assertEqual(str(DashboardTile.objects.get(id=tile_id).parent_group_id), group["id"])

    def test_group_rejects_cross_dashboard_membership(self) -> None:
        group = self._create_group("Acquisition")
        other_dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "Other"})
        _, other_dashboard = self.dashboard_api.create_text_tile(other_dashboard_id, text="Other tile")

        response = self.client.post(
            f"/api/projects/{self.team.id}/dashboards/{self.dashboard_id}/groups/move-tile/",
            {"tile_id": other_dashboard["tiles"][0]["id"], "group_id": group["id"]},
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_duplicate_dashboard_preserves_section_positions(self) -> None:
        self._create_group("First")
        self._create_group("Second")

        _, duplicated = self.dashboard_api.create_dashboard(
            {"name": "copy", "use_dashboard": self.dashboard_id, "duplicate_tiles": True}
        )

        self.assertEqual(
            [(group["name"], group["position"]) for group in duplicated["groups"]],
            [("First", 0), ("Second", 1)],
        )

    def test_template_preserves_named_and_anonymous_section_order(self) -> None:
        template = DashboardTemplate(
            template_name="Grouped template",
            dashboard_description="",
            dashboard_filters={},
            tags=[],
            tiles=[
                {"type": "TEXT", "body": "Before", "layouts": {"sm": {"x": 0, "y": 0, "w": 12, "h": 2}}},
                {
                    "type": "GROUP",
                    "group_key": "acquisition",
                    "name": "Acquisition",
                    "layouts": {"sm": {"x": 0, "y": 3, "w": 12, "h": 1}},
                },
                {
                    "type": "TEXT",
                    "group_key": "acquisition",
                    "body": "Signups",
                    "layouts": {"sm": {"x": 0, "y": 4, "w": 12, "h": 2}},
                },
                {
                    "type": "TEXT",
                    "group_key": "unknown",
                    "body": "After",
                    "layouts": {"sm": {"x": 0, "y": 7, "w": 12, "h": 2}},
                },
            ],
        )
        dashboard = Dashboard.objects.create(team=self.team, name="From template")

        create_from_template(dashboard, template, self.user)

        groups = list(dashboard.groups.order_by("position"))
        self.assertEqual([(group.name, group.position) for group in groups], [(None, 0), ("Acquisition", 1), (None, 2)])
        self.assertEqual([group.member_tiles.get().text.body for group in groups], ["Before", "Signups", "After"])

    def test_template_unknown_group_key_without_headers_stays_ungrouped(self) -> None:
        template = DashboardTemplate(
            template_name="Unknown key template",
            dashboard_description="",
            dashboard_filters={},
            tags=[],
            tiles=[
                {
                    "type": "TEXT",
                    "group_key": "unknown",
                    "body": "Signups",
                    "layouts": {"sm": {"x": 0, "y": 1, "w": 12, "h": 2}},
                }
            ],
        )
        dashboard = Dashboard.objects.create(team=self.team, name="From unknown template")

        create_from_template(dashboard, template, self.user)

        self.assertFalse(dashboard.groups.exists())
        self.assertIsNone(DashboardTile.objects.get(dashboard=dashboard).parent_group_id)
