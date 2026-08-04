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

    def test_group_lifecycle_and_tile_membership(self) -> None:
        create_response = self.client.post(
            f"/api/projects/{self.team.id}/dashboards/{self.dashboard_id}/groups/",
            {"name": "Acquisition"},
        )
        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
        group = create_response.json()
        self.assertEqual(group["name"], "Acquisition")
        self.assertEqual(group["layouts"]["sm"], {"x": 0, "y": 0, "w": 12, "h": 1})

        _, dashboard = self.dashboard_api.create_text_tile(self.dashboard_id, text="Signups")
        tile_id = dashboard["tiles"][0]["id"]
        move_response = self.client.post(
            f"/api/projects/{self.team.id}/dashboards/{self.dashboard_id}/groups/move-tile/",
            {"tile_id": tile_id, "group_id": group["id"]},
        )
        self.assertEqual(move_response.status_code, status.HTTP_200_OK)
        self.assertEqual(move_response.json()["parent_group_id"], group["id"])

        dashboard_response = self.client.get(f"/api/projects/{self.team.id}/dashboards/{self.dashboard_id}/")
        self.assertEqual(dashboard_response.status_code, status.HTTP_200_OK)
        self.assertEqual(dashboard_response.json()["groups"][0]["member_tile_ids"], [tile_id])
        self.assertEqual(len(dashboard_response.json()["tiles"]), 1)

        delete_response = self.client.post(
            f"/api/projects/{self.team.id}/dashboards/{self.dashboard_id}/groups/delete/",
            {"group_id": group["id"], "member_handling": "move_to_ungrouped"},
        )
        self.assertEqual(delete_response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(DashboardGroup.all_teams.filter(id=group["id"]).exists())
        self.assertIsNone(DashboardTile.objects.get(id=tile_id).parent_group_id)

    def test_group_rejects_cross_dashboard_membership(self) -> None:
        group_response = self.client.post(
            f"/api/projects/{self.team.id}/dashboards/{self.dashboard_id}/groups/",
            {"name": "Acquisition"},
        )
        other_dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "Other"})
        _, other_dashboard = self.dashboard_api.create_text_tile(other_dashboard_id, text="Other tile")

        response = self.client.post(
            f"/api/projects/{self.team.id}/dashboards/{self.dashboard_id}/groups/move-tile/",
            {"tile_id": other_dashboard["tiles"][0]["id"], "group_id": group_response.json()["id"]},
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_template_remaps_group_membership(self) -> None:
        template = DashboardTemplate(
            template_name="Grouped template",
            dashboard_description="",
            dashboard_filters={},
            tags=[],
            tiles=[
                {
                    "type": "GROUP",
                    "group_key": "acquisition",
                    "name": "Acquisition",
                    "layouts": {"sm": {"x": 0, "y": 0, "w": 12, "h": 1}},
                },
                {
                    "type": "TEXT",
                    "group_key": "acquisition",
                    "body": "Signups",
                    "layouts": {"sm": {"x": 0, "y": 1, "w": 12, "h": 2}},
                },
            ],
        )
        dashboard = Dashboard.objects.create(team=self.team, name="From template")

        create_from_template(dashboard, template, self.user)

        group = dashboard.groups.get()
        self.assertEqual(group.name, "Acquisition")
        self.assertEqual(group.member_tiles.get().text.body, "Signups")
