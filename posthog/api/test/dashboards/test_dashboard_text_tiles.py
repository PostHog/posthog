from unittest import mock

from rest_framework import status

from posthog.api.test.dashboards import DashboardAPI
from posthog.test.base import APIBaseTest, QueryMatchingTest


class TestDashboardTextTiles(APIBaseTest, QueryMatchingTest):
    def setUp(self) -> None:
        super().setUp()
        self.dashboard_api = DashboardAPI(self.client, self.team, self.assertEqual)

    def test_can_add_a_single_text_tile_to_a_dashboard(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard"})

        update_response = self.client.patch(
            f"/api/projects/{self.team.id}/dashboards/{dashboard_id}", {"text_tiles": [{"body": "I AM TEXT!"}]}
        )
        self.assertEqual(update_response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            update_response.json()["text_tiles"], [{"id": mock.ANY, "layouts": {}, "color": None, "body": "I AM TEXT!"}]
        )

    def test_can_update_text_tiles_on_a_dashboard(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard"})

        update_response = self.client.patch(
            f"/api/projects/{self.team.id}/dashboards/{dashboard_id}",
            {"text_tiles": [{"body": "I AM TEXT!"}, {"body": "I AM ALSO TEXT!"}]},
        )
        self.assertEqual(update_response.status_code, status.HTTP_200_OK)

        tiles = update_response.json()["text_tiles"]
        tiles[0]["color"] = "red"

        self.client.patch(f"/api/projects/{self.team.id}/dashboards/{dashboard_id}", {"text_tiles": tiles})
        self.assertEqual(update_response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            update_response.json()["text_tiles"],
            [
                {"id": tiles[0]["id"], "layouts": {}, "color": "red", "body": "I AM TEXT!"},
                {"body": "I AM ALSO TEXT!", "color": None, "id": tiles[1]["id"], "layouts": {}},
            ],
        )
