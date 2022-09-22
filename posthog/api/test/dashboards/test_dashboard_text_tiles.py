from datetime import timedelta
from typing import Dict, Union
from unittest import mock

from freezegun import freeze_time
from rest_framework import status

from posthog.api.test.dashboards import DashboardAPI
from posthog.models import DashboardTile, Text, User
from posthog.test.base import APIBaseTest, QueryMatchingTest


class TestDashboardTextTiles(APIBaseTest, QueryMatchingTest):
    def setUp(self) -> None:
        super().setUp()
        self.dashboard_api = DashboardAPI(self.client, self.team, self.assertEqual)

    @freeze_time("2022-04-01 12:45")
    def test_can_get_a_single_text_tile_on_a_dashboard(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard"})

        tile_text = Text.objects.create(body="I AM TEXT!", team=self.team)
        tile = DashboardTile.objects.create(dashboard_id=dashboard_id, text=tile_text)

        dashboard_json = self.dashboard_api.get_dashboard(dashboard_id)

        self.assertEqual(
            dashboard_json["tiles"],
            [
                {
                    "id": tile.id,
                    "filters_hash": None,
                    "last_refresh": None,
                    "refreshing": None,
                    "refresh_attempt": None,
                    "layouts": {},
                    "color": None,
                    "dashboard": dashboard_id,
                    "insight": None,
                    "text": {
                        "body": "I AM TEXT!",
                        "created_by": None,
                        "id": tile_text.id,
                        "last_modified_at": "2022-04-01T12:45:00Z",
                        "last_modified_by": None,
                        "team": self.team.id,
                    },
                }
            ],
        )

    @freeze_time("2022-04-01 12:45")
    def test_can_add_a_single_text_tile_to_a_dashboard(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard"})

        update_response = self.client.patch(
            f"/api/projects/{self.team.id}/dashboards/{dashboard_id}", {"tiles": [{"text": {"body": "I AM TEXT!"}}]}
        )
        self.assertEqual(update_response.status_code, status.HTTP_200_OK, update_response.json())
        self.maxDiff = None
        self.assertEqual(len(update_response.json()["tiles"]), 1)
        assert update_response.json()["tiles"][0] == {
            "id": mock.ANY,
            "layouts": {},
            "color": None,
            "text": {
                "id": mock.ANY,
                "body": "I AM TEXT!",
                "created_by": self._serialised_user(self.user),
                "last_modified_at": "2022-04-01T12:45:00Z",
                "last_modified_by": None,
                "team": self.team.id,
            },
            "refresh_attempt": None,
            "refreshing": None,
            "last_refresh": None,
            "insight": None,
            "filters_hash": None,
            "dashboard": dashboard_id,
        }

    def test_can_remove_text_tiles_from_dashboard(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard"})

        update_response = self.client.patch(
            f"/api/projects/{self.team.id}/dashboards/{dashboard_id}",
            {
                "tiles": [
                    {"text": {"body": "I AM TEXT!"}},
                    {"text": {"body": "YOU AM TEXT"}},
                    {"text": {"body": "THEY AM TEXT"}},
                ]
            },
        )
        self.assertEqual(update_response.status_code, status.HTTP_200_OK)
        created_tiles = update_response.json()["tiles"]
        self.assertEqual(len(created_tiles), 3)

        update_response = self.client.patch(
            f"/api/projects/{self.team.id}/dashboards/{dashboard_id}",
            {"tiles": created_tiles[1:]},
        )
        self.assertEqual(update_response.status_code, status.HTTP_200_OK, update_response.json())
        self.assertEqual(len(update_response.json()["tiles"]), 2)

    def test_can_update_text_tiles_on_a_dashboard(self) -> None:
        with freeze_time("2022-04-01 12:45") as frozen_time:
            self.maxDiff = None

            dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard"})

            update_response = self.client.patch(
                f"/api/projects/{self.team.id}/dashboards/{dashboard_id}",
                {"tiles": [{"body": "I AM TEXT!"}, {"body": "I AM ALSO TEXT!"}]},
            )
            self.assertEqual(update_response.status_code, status.HTTP_200_OK)

            tiles = update_response.json()["tiles"]
            tiles[0]["color"] = "red"

            self.client.patch(f"/api/projects/{self.team.id}/dashboards/{dashboard_id}", {"tiles": tiles})
            self.assertEqual(update_response.status_code, status.HTTP_200_OK)

            self.assertEqual(
                update_response.json()["tiles"],
                [
                    {
                        "id": tiles[0]["id"],
                        "layouts": {},
                        "color": "red",
                        "body": "I AM TEXT!",
                        "created_by": self._serialised_user(self.user),
                        "last_modified_at": "2022-04-01T12:45:00Z",
                        "last_modified_by": None,
                    },
                    {
                        "body": "I AM ALSO TEXT!",
                        "color": None,
                        "id": tiles[1]["id"],
                        "layouts": {},
                        "created_by": self._serialised_user(self.user),
                        "last_modified_at": "2022-04-01T12:45:00Z",
                        "last_modified_by": None,
                    },
                ],
            )

            new_user: User = User.objects.create_and_join(
                organization=self.organization, email="second@posthog.com", password="Secretive"
            )
            self.client.force_login(new_user)
            tiles[1]["body"] = "amended text"

            frozen_time.tick(delta=timedelta(hours=4))

            different_user_update_response = self.client.patch(
                f"/api/projects/{self.team.id}/dashboards/{dashboard_id}", {"tiles": tiles}
            )
            self.assertEqual(different_user_update_response.status_code, status.HTTP_200_OK)

            self.assertEqual(
                different_user_update_response.json()["tiles"],
                [
                    {
                        "id": tiles[0]["id"],
                        "layouts": {},
                        "color": "red",
                        "body": "I AM TEXT!",
                        "created_by": self._serialised_user(self.user),
                        "last_modified_at": "2022-04-01T12:45:00Z",
                        "last_modified_by": self._serialised_user(self.user),
                    },
                    {
                        "body": "amended text",
                        "color": None,
                        "id": tiles[1]["id"],
                        "layouts": {},
                        "created_by": self._serialised_user(self.user),
                        "last_modified_at": "2022-04-01T16:45:00Z",
                        "last_modified_by": self._serialised_user(new_user),
                    },
                ],
            )

    def test_dashboard_item_layout_can_update_text_tiles(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "asdasd", "pinned": True})

        response = self.client.patch(
            f"/api/projects/{self.team.id}/dashboards/{dashboard_id}",
            {"tiles": [{"text": {"body": "Woah, text"}}]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        text_tile_id = response.json()["tiles"][0]["id"]

        response = self.client.patch(
            f"/api/projects/{self.team.id}/dashboards/{dashboard_id}",
            {
                "tile_layouts": {
                    "text_tiles": [
                        {
                            "id": text_tile_id,
                            "layouts": {
                                "lg": {"x": "0", "y": "0", "w": "6", "h": "5"},
                                "sm": {
                                    "w": "7",
                                    "h": "5",
                                    "x": "0",
                                    "y": "0",
                                    "moved": "False",
                                    "static": "False",
                                },
                                "xs": {"x": "0", "y": "0", "w": "6", "h": "5"},
                                "xxs": {"x": "0", "y": "0", "w": "2", "h": "5"},
                            },
                        }
                    ]
                }
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        dashboard_json = self.dashboard_api.get_dashboard(dashboard_id)
        text_tile_layouts = dashboard_json["tiles"][0]["layouts"]
        self.assertTrue("lg" in text_tile_layouts)

    @staticmethod
    def _serialised_user(user: User) -> Dict[str, Union[int, str]]:
        return {
            "distinct_id": user.distinct_id,
            "email": user.email,
            "first_name": "",
            "id": user.id,
            "uuid": str(user.uuid),
        }
