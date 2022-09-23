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
    def test_can_list_a_single_text_tile_for_a_dashboard(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard"})

        tile_text = Text.objects.create(body="I AM TEXT!", team=self.team)
        tile = DashboardTile.objects.create(dashboard_id=dashboard_id, text=tile_text)

        response = self.client.get(f"/api/projects/{self.team.id}/dashboards/{dashboard_id}/tiles")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        tiles_json = response.json()

        self.assertEqual(
            tiles_json,
            {
                "count": 1,
                "next": None,
                "previous": None,
                "results": [
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
            },
        )

    @freeze_time("2022-04-01 12:45")
    def test_can_add_a_single_text_tile_to_a_dashboard(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard"})

        update_response = self.client.post(
            f"/api/projects/{self.team.id}/dashboards/{dashboard_id}/tiles", {"text": {"body": "I AM TEXT!"}}
        )

        self.assertEqual(update_response.status_code, status.HTTP_201_CREATED, update_response.json())
        self.maxDiff = None
        expected_tile = self._expected_tile_with_text(dashboard_id, "I AM TEXT!")
        self.assertEqual(
            update_response.json(),
            expected_tile,
        )

        dashboard_json = self.dashboard_api.get_dashboard(dashboard_id)
        self.assertEqual(dashboard_json["tiles"], [expected_tile])

    @freeze_time("2022-04-01 12:45")
    def test_can_add_a_multiple_text_tiles_to_a_dashboard(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard"})

        update_response = self.client.post(
            f"/api/projects/{self.team.id}/dashboards/{dashboard_id}/tiles",
            [{"text": {"body": "I AM TEXT!"}}, {"text": {"body": "I AM ALSO TEXT!"}}],
        )

        self.assertEqual(update_response.status_code, status.HTTP_201_CREATED, update_response.json())
        self.maxDiff = None
        expected_tiles = [
            self._expected_tile_with_text(dashboard_id, "I AM TEXT!"),
            self._expected_tile_with_text(dashboard_id, "I AM ALSO TEXT!"),
        ]
        self.assertEqual(
            update_response.json(),
            expected_tiles,
        )

        dashboard_json = self.dashboard_api.get_dashboard(dashboard_id)
        self.assertEqual(dashboard_json["tiles"], expected_tiles)

    def _expected_tile_with_text(self, dashboard_id: int, body: str):
        return {
            "id": mock.ANY,
            "layouts": {},
            "color": None,
            "text": {
                "id": mock.ANY,
                "body": body,
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

            create_tiles_response = self.client.post(
                f"/api/projects/{self.team.id}/dashboards/{dashboard_id}/tiles",
                [{"text": {"body": "I AM TEXT!"}}, {"text": {"body": "I AM ALSO TEXT!"}}],
            )
            self.assertEqual(create_tiles_response.status_code, status.HTTP_201_CREATED)

            tiles = create_tiles_response.json()
            tiles[0]["color"] = "red"

            update_tile_response = self.client.patch(
                f"/api/projects/{self.team.id}/dashboards/{dashboard_id}/tiles/{tiles[0]['id']}", tiles[0]
            )
            self.assertEqual(update_tile_response.status_code, status.HTTP_200_OK)

            self.assertEqual(
                update_tile_response.json(),
                {
                    "id": tiles[0]["id"],
                    "layouts": {},
                    "color": "red",
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
                },
            )

            new_user: User = User.objects.create_and_join(
                organization=self.organization, email="second@posthog.com", password="Secretive"
            )
            self.client.force_login(new_user)
            tiles[1]["text"]["body"] = "amended text"

            frozen_time.tick(delta=timedelta(hours=4))

            different_user_update_response = self.client.patch(
                f"/api/projects/{self.team.id}/dashboards/{dashboard_id}/tiles/{tiles[1]['id']}", tiles[1]
            )
            self.assertEqual(different_user_update_response.status_code, status.HTTP_200_OK)

            dashboard_json = self.dashboard_api.get_dashboard(dashboard_id)
            updated_tiles = sorted(dashboard_json["tiles"], key=lambda d: d["id"])
            self.assertEqual(len(updated_tiles), 2)
            self.assertEqual(
                updated_tiles[0],
                {
                    "id": tiles[0]["id"],
                    "layouts": {},
                    "color": "red",
                    "text": {
                        "id": tiles[0]["text"]["id"],
                        "team": self.team.id,
                        "body": "I AM TEXT!",
                        "created_by": self._serialised_user(self.user),
                        "last_modified_at": "2022-04-01T12:45:00Z",
                        "last_modified_by": self._serialised_user(self.user),
                    },
                    "refresh_attempt": None,
                    "refreshing": None,
                    "last_refresh": None,
                    "insight": None,
                    "filters_hash": None,
                    "dashboard": dashboard_id,
                },
            )
            self.assertEqual(
                updated_tiles[1],
                {
                    "color": None,
                    "id": tiles[1]["id"],
                    "layouts": {},
                    "text": {
                        "id": tiles[1]["text"]["id"],
                        "team": self.team.id,
                        "body": "amended text",
                        "created_by": self._serialised_user(self.user),
                        "last_modified_at": "2022-04-01T16:45:00Z",
                        "last_modified_by": self._serialised_user(new_user),
                    },
                    "refresh_attempt": None,
                    "refreshing": None,
                    "last_refresh": None,
                    "insight": None,
                    "filters_hash": None,
                    "dashboard": dashboard_id,
                },
            )

    def test_dashboard_item_layout_can_update_text_tiles(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "asdasd", "pinned": True})

        response = self.client.post(
            f"/api/projects/{self.team.id}/dashboards/{dashboard_id}/tiles",
            {"text": {"body": "Woah, text"}},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        text_tile_id = response.json()["id"]

        add_layouts_response = self.client.patch(
            f"/api/projects/{self.team.id}/dashboards/{dashboard_id}/tiles/{text_tile_id}",
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
            },
        )
        self.assertEqual(add_layouts_response.status_code, status.HTTP_200_OK)

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
