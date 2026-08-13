from posthog.test.base import APIBaseTest
from unittest.mock import patch

from rest_framework import status

from posthog.api.test.dashboards import DashboardAPI

from products.dashboards.backend.models.dashboard_group import DashboardGroup
from products.dashboards.backend.models.dashboard_tile import DashboardTile


class TestDashboardGroups(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.dashboard_api = DashboardAPI(self.client, self.team, self.assertEqual)
        self.dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "Grouped dashboard"})
        self._groups_flag_patcher = patch(
            "products.dashboards.backend.api.dashboard.dashboard_groups_enabled",
            return_value=True,
        )
        self._groups_flag_patcher.start()

    def tearDown(self) -> None:
        self._groups_flag_patcher.stop()
        super().tearDown()

    def test_group_lifecycle_and_tile_membership(self) -> None:
        create_response = self.client.post(
            f"/api/projects/{self.team.id}/dashboards/{self.dashboard_id}/groups/",
            {"name": "Acquisition"},
        )
        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
        group = create_response.json()
        self.assertEqual(group["name"], "Acquisition")
        self.assertEqual(group["layouts"]["sm"], {"x": 0, "y": 0, "w": 12, "h": 1})

        rename_response = self.client.post(
            f"/api/projects/{self.team.id}/dashboards/{self.dashboard_id}/groups/update/",
            {"group_id": group["id"], "name": "Activation"},
        )
        self.assertEqual(rename_response.status_code, status.HTTP_200_OK)
        self.assertEqual(rename_response.json()["name"], "Activation")

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

    def test_delete_tiles_soft_deletes_members(self) -> None:
        group = self.client.post(
            f"/api/projects/{self.team.id}/dashboards/{self.dashboard_id}/groups/",
            {"name": "Acquisition"},
        ).json()
        _, dashboard = self.dashboard_api.create_text_tile(self.dashboard_id, text="Signups")
        tile_id = dashboard["tiles"][0]["id"]
        self.client.post(
            f"/api/projects/{self.team.id}/dashboards/{self.dashboard_id}/groups/move-tile/",
            {"tile_id": tile_id, "group_id": group["id"]},
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/dashboards/{self.dashboard_id}/groups/delete/",
            {"group_id": group["id"], "member_handling": "delete_tiles"},
        )

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(DashboardTile.objects.filter(id=tile_id).exists())
        self.assertTrue(DashboardTile.objects_including_soft_deleted.filter(id=tile_id, deleted=True).exists())

    def test_moving_a_group_moves_its_members(self) -> None:
        group = self.client.post(
            f"/api/projects/{self.team.id}/dashboards/{self.dashboard_id}/groups/",
            {"name": "Acquisition"},
        ).json()
        _, dashboard = self.dashboard_api.create_text_tile(self.dashboard_id, text="Signups")
        tile = dashboard["tiles"][0]
        self.client.post(
            f"/api/projects/{self.team.id}/dashboards/{self.dashboard_id}/groups/move-tile/",
            {"tile_id": tile["id"], "group_id": group["id"], "layouts": {"sm": {"x": 0, "y": 1, "w": 12, "h": 2}}},
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/dashboards/{self.dashboard_id}/groups/update/",
            {"group_id": group["id"], "layouts": {"sm": {"x": 0, "y": 5, "w": 12, "h": 1}}},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(DashboardTile.objects.get(id=tile["id"]).layouts["sm"]["y"], 6)

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

    def test_cannot_move_a_group_header_into_a_group(self) -> None:
        group = self.client.post(
            f"/api/projects/{self.team.id}/dashboards/{self.dashboard_id}/groups/",
            {"name": "Acquisition"},
        ).json()
        other = self.client.post(
            f"/api/projects/{self.team.id}/dashboards/{self.dashboard_id}/groups/",
            {"name": "Retention"},
        ).json()

        response = self.client.post(
            f"/api/projects/{self.team.id}/dashboards/{self.dashboard_id}/groups/move-tile/",
            {"tile_id": group["tile_id"], "group_id": other["id"]},
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_copy_dashboard_remaps_group_membership(self) -> None:
        group = self.client.post(
            f"/api/projects/{self.team.id}/dashboards/{self.dashboard_id}/groups/",
            {"name": "Acquisition"},
        ).json()
        _, dashboard = self.dashboard_api.create_text_tile(self.dashboard_id, text="Signups")
        tile_id = dashboard["tiles"][0]["id"]
        self.client.post(
            f"/api/projects/{self.team.id}/dashboards/{self.dashboard_id}/groups/move-tile/",
            {"tile_id": tile_id, "group_id": group["id"]},
        )

        _, copied = self.dashboard_api.create_dashboard({"name": "copy", "use_dashboard": self.dashboard_id})

        self.assertEqual(len(copied["groups"]), 1)
        self.assertNotEqual(copied["groups"][0]["id"], group["id"])
        self.assertEqual(copied["groups"][0]["name"], "Acquisition")
        self.assertEqual(len(copied["tiles"]), 1)
        self.assertEqual(copied["tiles"][0]["parent_group_id"], copied["groups"][0]["id"])
        self.assertEqual(copied["groups"][0]["member_tile_ids"], [copied["tiles"][0]["id"]])

    def test_mutations_are_forbidden_when_the_flag_is_off(self) -> None:
        self._groups_flag_patcher.stop()
        try:
            response = self.client.post(
                f"/api/projects/{self.team.id}/dashboards/{self.dashboard_id}/groups/",
                {"name": "Acquisition"},
            )
        finally:
            self._groups_flag_patcher.start()

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_moving_a_tile_to_another_dashboard_clears_group_membership(self) -> None:
        group = self.client.post(
            f"/api/projects/{self.team.id}/dashboards/{self.dashboard_id}/groups/",
            {"name": "Acquisition"},
        ).json()
        _, dashboard = self.dashboard_api.create_text_tile(self.dashboard_id, text="Signups")
        tile = dashboard["tiles"][0]
        self.client.post(
            f"/api/projects/{self.team.id}/dashboards/{self.dashboard_id}/groups/move-tile/",
            {"tile_id": tile["id"], "group_id": group["id"]},
        )
        other_dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "Other"})

        response = self.client.patch(
            f"/api/projects/{self.team.id}/dashboards/{self.dashboard_id}/move_tile",
            {"tile": tile, "to_dashboard": other_dashboard_id},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        moved = DashboardTile.objects.get(id=tile["id"])
        self.assertEqual(moved.dashboard_id, other_dashboard_id)
        self.assertIsNone(moved.parent_group_id)
