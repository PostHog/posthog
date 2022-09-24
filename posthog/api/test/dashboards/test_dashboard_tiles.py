from datetime import timedelta
from typing import Dict, Optional, Union
from unittest import mock

from freezegun import freeze_time
from rest_framework import status

from posthog.api.test.dashboards import DashboardAPI
from posthog.models import User
from posthog.test.base import APIBaseTest, QueryMatchingTest


class TestDashboardTiles(APIBaseTest, QueryMatchingTest):
    def setUp(self) -> None:
        super().setUp()
        self.dashboard_api = DashboardAPI(self.client, self.team, self.assertEqual)

    def _expected_text(
        self,
        body: str,
        created_by: Optional[User] = None,
        last_modified_by: Optional[User] = None,
        text_id: Optional[int] = None,
        last_modified_at: str = "2022-04-01T12:45:00Z",
    ) -> Dict:
        if not created_by:
            created_by = self.user

        if not text_id:
            text_id = mock.ANY

        return {
            "id": text_id,
            "body": body,
            "created_by": self._serialised_user(created_by),
            "last_modified_at": last_modified_at,
            "last_modified_by": self._serialised_user(last_modified_by),
            "team": self.team.id,
        }

    def _expected_tile_with_text(
        self,
        dashboard_id: int,
        body: str,
        tile_id: Optional[int] = None,
        created_by: Optional[User] = None,
        last_modified_by: Optional[User] = None,
        text_id: Optional[int] = None,
        color: Optional[str] = None,
        last_modified_at: str = "2022-04-01T12:45:00Z",
    ) -> Dict:
        if not tile_id:
            tile_id = mock.ANY
        return {
            "id": tile_id,
            "layouts": {},
            "color": color,
            "text": self._expected_text(
                body,
                created_by=created_by,
                last_modified_by=last_modified_by,
                text_id=text_id,
                last_modified_at=last_modified_at,
            ),
            "refresh_attempt": None,
            "refreshing": None,
            "last_refresh": None,
            "insight": None,
            "filters_hash": None,
            "dashboard": dashboard_id,
        }

    @freeze_time("2022-04-01 12:45")
    def test_can_get_a_single_text_tile_on_a_dashboard(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard"})

        tile_id, tile_json = self.dashboard_api.create_text_tile(dashboard_id)

        dashboard_json = self.dashboard_api.get_dashboard(dashboard_id)

        assert dashboard_json["tiles"] == [
            self._expected_tile_with_text(
                dashboard_id, body="I AM TEXT!", text_id=tile_json["text"]["id"], tile_id=tile_id
            )
        ]

    @freeze_time("2022-04-01 12:45")
    def test_can_list_a_single_text_tile_for_a_dashboard(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard"})

        tile_id, tile_json = self.dashboard_api.create_text_tile(dashboard_id, "I AM TEXT!")

        response = self.client.get(f"/api/projects/{self.team.id}/dashboards/{dashboard_id}/tiles")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        tiles_json = response.json()

        assert tiles_json == {
            "count": 1,
            "next": None,
            "previous": None,
            "results": [
                self._expected_tile_with_text(
                    dashboard_id, body="I AM TEXT!", text_id=tile_json["text"]["id"], tile_id=tile_id
                )
            ],
        }

    @freeze_time("2022-04-01 12:45")
    def test_can_add_a_single_text_tile_to_a_dashboard(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard"})

        _, tile_json = self.dashboard_api.create_text_tile(dashboard_id)
        self.maxDiff = None
        expected_tile = self._expected_tile_with_text(dashboard_id, "I AM TEXT!")
        self.assertEqual(
            tile_json,
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

    def test_can_remove_text_tiles_from_dashboard(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard"})

        update_response = self.client.post(
            f"/api/projects/{self.team.id}/dashboards/{dashboard_id}/tiles",
            [
                {"text": {"body": "I AM TEXT!"}},
                {"text": {"body": "YOU AM TEXT"}},
                {"text": {"body": "THEY AM TEXT"}},
            ],
        )
        self.assertEqual(update_response.status_code, status.HTTP_201_CREATED)
        created_tiles = update_response.json()
        self.assertEqual(len(created_tiles), 3)

        delete_response = self.client.delete(
            f"/api/projects/{self.team.id}/dashboards/{dashboard_id}/tiles/{created_tiles[0]['id']}"
        )
        self.assertEqual(delete_response.status_code, status.HTTP_204_NO_CONTENT)

        dashboard_json = self.dashboard_api.get_dashboard(dashboard_id)
        tiles = dashboard_json["tiles"]
        self.assertCountEqual([t["id"] for t in tiles], [t["id"] for t in created_tiles[1:]])

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

            assert update_tile_response.json() == self._expected_tile_with_text(
                dashboard_id, "I AM TEXT!", last_modified_by=self.user, color="red"
            )

            new_user: User = User.objects.create_and_join(
                organization=self.organization, email="second@posthog.com", password="Secretive"
            )
            self.client.force_login(new_user)
            tiles[1]["text"]["body"] = "amended text"

            frozen_time.tick(delta=timedelta(hours=4))

            self.assertIn("id", tiles[1])
            self.assertIn("id", tiles[1]["text"])

            different_user_update_response = self.client.patch(
                f"/api/projects/{self.team.id}/dashboards/{dashboard_id}/tiles/{tiles[1]['id']}", tiles[1]
            )
            self.assertEqual(different_user_update_response.status_code, status.HTTP_200_OK)

            dashboard_json = self.dashboard_api.get_dashboard(dashboard_id)
            updated_tiles = sorted(dashboard_json["tiles"], key=lambda d: d["id"])

            assert updated_tiles == [
                self._expected_tile_with_text(
                    dashboard_id,
                    "I AM TEXT!",
                    color="red",
                    last_modified_by=self.user,
                    tile_id=tiles[0]["id"],
                    text_id=tiles[0]["text"]["id"],
                ),
                self._expected_tile_with_text(
                    dashboard_id,
                    "amended text",
                    last_modified_at="2022-04-01T16:45:00Z",
                    last_modified_by=new_user,
                    tile_id=tiles[1]["id"],
                    text_id=tiles[1]["text"]["id"],
                ),
            ]

    def test_dashboard_item_layout_can_update_text_tiles(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard", "pinned": True})

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

    def test_can_have_mixed_collection_of_tiles(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard", "pinned": True})
        insight_id, _ = self.dashboard_api.create_insight({})
        self.fail("not written yet")

    @staticmethod
    def _serialised_user(user: Optional[User]) -> Optional[Dict[str, Union[int, str]]]:
        if user is None:
            return None

        return {
            "distinct_id": user.distinct_id,
            "email": user.email,
            "first_name": "",
            "id": user.id,
            "uuid": str(user.uuid),
        }
