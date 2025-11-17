import datetime
from typing import Optional, Union

from freezegun import freeze_time
from posthog.test.base import APIBaseTest, QueryMatchingTest
from unittest import mock

from django.test import override_settings

from rest_framework import status

from posthog.api.test.dashboards import DashboardAPI
from posthog.models import User


class TestDashboardTiles(APIBaseTest, QueryMatchingTest):
    def setUp(self) -> None:
        super().setUp()
        self.dashboard_api = DashboardAPI(self.client, self.team, self.assertEqual)

    @staticmethod
    def _serialised_user(user: Optional[User]) -> Optional[dict[str, Optional[Union[int, str]]]]:
        if user is None:
            return None

        return {
            "distinct_id": user.distinct_id,
            "email": user.email,
            "first_name": "",
            "last_name": "",
            "id": user.id,
            "uuid": str(user.uuid),
            "is_email_verified": None,
            "hedgehog_config": None,
            "role_at_organization": None,
        }

    def _expected_text(
        self,
        body: str,
        created_by: Optional[User] = None,
        last_modified_by: Optional[User] = None,
        text_id: Optional[int] = None,
        last_modified_at: str = "2022-04-01T12:45:00Z",
    ) -> dict:
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
        body: str,
        tile_id: Optional[int] = None,
        created_by: Optional[User] = None,
        last_modified_by: Optional[User] = None,
        text_id: Optional[int] = None,
        color: Optional[str] = None,
        last_modified_at: str = "2022-04-01T12:45:00Z",
    ) -> dict:
        if not tile_id:
            tile_id = mock.ANY
        return {
            "id": tile_id,
            "layouts": {},
            "order": 0,
            "color": color,
            "filters_overrides": {},
            "text": self._expected_text(
                body,
                created_by=created_by,
                last_modified_by=last_modified_by,
                text_id=text_id,
                last_modified_at=last_modified_at,
            ),
            "last_refresh": None,
            "is_cached": False,
            "insight": None,
        }

    @staticmethod
    def _tile_layout(lg: Optional[dict] = None) -> dict:
        if lg is None:
            lg = {"x": "0", "y": "0", "w": "6", "h": "5"}

        return {
            "lg": lg,
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
        }

    @freeze_time("2022-04-01 12:45")
    @override_settings(IN_UNIT_TESTING=True)
    def test_can_create_a_single_text_tile(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard"})

        dashboard_id, dashboard_json = self.dashboard_api.create_text_tile(dashboard_id, text="hello world")

        assert len(dashboard_json["tiles"]) == 1
        assert dashboard_json["tiles"][0] == self._expected_tile_with_text(
            body="hello world",
        )

    @override_settings(IN_UNIT_TESTING=True)
    def test_can_update_a_single_text_tile(self) -> None:
        with freeze_time("2022-04-01 12:45") as frozen_time:
            dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard"})

            dashboard_id, dashboard_json = self.dashboard_api.create_text_tile(dashboard_id, text="hello world")
            dashboard_id, dashboard_json = self.dashboard_api.create_text_tile(dashboard_id, text="ciao il mondo")

            assert len(dashboard_json["tiles"]) == 2
            tile_ids = sorted([tile["id"] for tile in dashboard_json["tiles"]])

            frozen_time.tick(delta=datetime.timedelta(hours=10))
            other_user = User.objects.create_and_join(organization=self.organization, email="", password="")
            self.client.force_login(other_user)
            updated_tile = {**dashboard_json["tiles"][0]}
            updated_tile["text"]["body"] = "anche ciao"
            dashboard_id, dashboard_json = self.dashboard_api.update_text_tile(dashboard_id, updated_tile)

            sorted_tiles = sorted(dashboard_json["tiles"], key=lambda x: x["id"])
            assert len(sorted_tiles) == 2

            assert sorted_tiles[0]["id"] == tile_ids[0]
            assert sorted_tiles[1]["id"] == tile_ids[1]

            # the edit to tile 0 has changed the text
            assert sorted_tiles[0]["text"]["body"] == "anche ciao"
            assert sorted_tiles[1]["text"]["body"] == "ciao il mondo"

            # created by is set for both tiles
            assert sorted_tiles[0]["text"]["created_by"]["id"] == self.user.id
            assert sorted_tiles[1]["text"]["created_by"]["id"] == self.user.id

            # tile 1 has never been modified so has no modified by user
            assert sorted_tiles[0]["text"]["last_modified_by"]["id"] == other_user.id
            assert sorted_tiles[1]["text"]["last_modified_by"] is None

            # tile 1 has not been modified, but tile 0 has. Tile 0 has a new modified at date
            assert sorted_tiles[0]["text"]["last_modified_at"] == "2022-04-01T22:45:00Z"
            assert sorted_tiles[1]["text"]["last_modified_at"] == "2022-04-01T12:45:00Z"

    def test_can_update_a_single_text_tile_color(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard"})

        dashboard_id, dashboard_json = self.dashboard_api.create_text_tile(dashboard_id, text="hello world")
        dashboard_id, dashboard_json = self.dashboard_api.create_text_tile(dashboard_id, text="ciao il mondo")

        assert len(dashboard_json["tiles"]) == 2
        tile_ids = [tile["id"] for tile in dashboard_json["tiles"]]

        updated_tile = {**dashboard_json["tiles"][0]}
        updated_tile["color"] = "purple"
        dashboard_id, dashboard_json = self.dashboard_api.update_text_tile(dashboard_id, updated_tile)

        assert len(dashboard_json["tiles"]) == 2
        assert {(t["id"], t["color"]) for t in dashboard_json["tiles"]} == {
            (tile_ids[0], "purple"),
            (tile_ids[1], None),
        }

    def test_can_remove_text_tiles_from_dashboard(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard"})

        dashboard_id, dashboard_json = self.dashboard_api.create_text_tile(dashboard_id, text="io sono testo")
        dashboard_id, dashboard_json = self.dashboard_api.create_text_tile(dashboard_id, text="soy texto")
        dashboard_id, dashboard_json = self.dashboard_api.create_text_tile(dashboard_id, text="i am text")
        dashboard_id, dashboard_json = self.dashboard_api.create_text_tile(dashboard_id, text="ich bin text")

        last_tile = dashboard_json["tiles"][-1]

        delete_response = self.client.patch(
            f"/api/projects/{self.team.id}/dashboards/{dashboard_id}",
            # can send just tile id and deleted flag
            {"tiles": [{"id": last_tile["id"], "deleted": True}]},
        )
        self.assertEqual(delete_response.status_code, status.HTTP_200_OK)

        dashboard_json = self.dashboard_api.get_dashboard(dashboard_id)
        tiles = dashboard_json["tiles"]
        assert len(tiles) == 3
        assert [t["text"]["body"] for t in tiles] == [
            "io sono testo",
            "soy texto",
            "i am text",
        ]

    def test_do_not_see_deleted_text_tiles_when_adding_new_ones(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard"})

        self.dashboard_api.create_text_tile(dashboard_id, text="io sono testo")
        dashboard_id, dashboard_json = self.dashboard_api.create_text_tile(dashboard_id, text="soy texto")

        assert len(dashboard_json["tiles"]) == 2

        self.dashboard_api.update_text_tile(dashboard_id, {**dashboard_json["tiles"][0], "deleted": True})

        dashboard_json = self.dashboard_api.get_dashboard(dashboard_id)
        assert len(dashboard_json["tiles"]) == 1

        _, with_another_tile_dashboard_json = self.dashboard_api.create_text_tile(
            dashboard_id, text="i am a third text"
        )
        assert len(with_another_tile_dashboard_json["tiles"]) == 2
        assert sorted([t["text"]["body"] for t in with_another_tile_dashboard_json["tiles"]]) == sorted(
            [
                "soy texto",
                "i am a third text",
            ]
        )

    def test_cannot_create_text_tile_with_body_over_4000_characters(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard"})

        # Test with exactly 4000 characters (should work)
        valid_text = "a" * 4000
        response = self.client.patch(
            f"/api/projects/{self.team.id}/dashboards/{dashboard_id}",
            {"tiles": [{"text": {"body": valid_text}}]},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Test with 4001 characters (should fail)
        invalid_text = "a" * 4001
        response = self.client.patch(
            f"/api/projects/{self.team.id}/dashboards/{dashboard_id}",
            {"tiles": [{"text": {"body": invalid_text}}]},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        response_data = response.json()
        self.assertEqual(response_data["type"], "validation_error")
        self.assertEqual(response_data["code"], "max_length")
        self.assertEqual(response_data["detail"], "Text body cannot exceed 4000 characters")
        self.assertEqual(response_data["attr"], "text__body")

    def test_cannot_update_text_tile_with_body_over_4000_characters(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard"})
        dashboard_id, dashboard_json = self.dashboard_api.create_text_tile(dashboard_id, text="hello world")

        tile = dashboard_json["tiles"][0]
        invalid_text = "b" * 4001

        response = self.client.patch(
            f"/api/projects/{self.team.id}/dashboards/{dashboard_id}",
            {"tiles": [{"id": tile["id"], "text": {**tile["text"], "body": invalid_text}}]},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        response_data = response.json()
        self.assertEqual(response_data["type"], "validation_error")
        self.assertEqual(response_data["code"], "max_length")
        self.assertEqual(response_data["detail"], "Text body cannot exceed 4000 characters")
        self.assertEqual(response_data["attr"], "text__body")
