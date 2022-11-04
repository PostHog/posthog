import datetime
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

    def _expected_saved_filter(
        self,
        name: Optional[str],
        derived_name: Optional[str],
        filters: Optional[Dict] = None,
        created_by: Optional[User] = None,
        last_modified_by: Optional[User] = None,
        saved_filter_id: Optional[int] = None,
        last_modified_at: str = "2022-04-01T12:45:00Z",
    ) -> Dict:
        if not created_by:
            created_by = self.user

        if not saved_filter_id:
            saved_filter_id = mock.ANY

        if not filters:
            filters = {}

        return {
            "created_by": self._serialised_user(created_by),
            "deleted": None,
            "derived_name": derived_name if derived_name else "",
            "filters": filters,
            "id": saved_filter_id,
            "last_modified_at": last_modified_at,
            "last_modified_by": self._serialised_user(last_modified_by),
            "name": name,
            "team": self.team.id,
        }

    def _expected_tile_with_saved_filter(
        self,
        name: Optional[str],
        derived_name: Optional[str] = None,
        filters: Optional[Dict] = None,
        created_by: Optional[User] = None,
        last_modified_by: Optional[User] = None,
        saved_filter_id: Optional[int] = None,
        tile_id: Optional[int] = None,
        last_modified_at: str = "2022-04-01T12:45:00Z",
        color: Optional[str] = None,
    ) -> Dict:
        if not saved_filter_id:
            saved_filter_id = mock.ANY
        if not tile_id:
            tile_id = mock.ANY

        return {
            "id": tile_id,
            "layouts": {},
            "color": color,
            "saved_filter": self._expected_saved_filter(
                name,
                derived_name,
                filters,
                created_by=created_by,
                last_modified_by=last_modified_by,
                saved_filter_id=saved_filter_id,
                last_modified_at=last_modified_at,
            ),
            "refresh_attempt": None,
            "refreshing": None,
            "last_refresh": None,
            "insight": None,
            "text": None,
            "filters_hash": None,
        }

    @staticmethod
    def _tile_layout(lg: Optional[Dict] = None) -> Dict:
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
    def test_can_create_a_single_saved_filter_tile(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard"})

        dashboard_id, dashboard_json = self.dashboard_api.create_saved_filter_tile(
            dashboard_id, name="hello world", filters={"something": "here"}
        )

        assert len(dashboard_json["tiles"]) == 1
        assert dashboard_json["tiles"][0] == self._expected_tile_with_saved_filter(
            name="hello world", filters={"something": "here"}
        )

    def test_can_update_a_single_saved_filter_tile(self) -> None:
        with freeze_time("2022-04-01 12:45") as frozen_time:
            dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard"})

            dashboard_id, dashboard_json = self.dashboard_api.create_saved_filter_tile(
                dashboard_id, name="hello world", filters={"a": "b"}
            )
            dashboard_id, dashboard_json = self.dashboard_api.create_saved_filter_tile(
                dashboard_id, name="ciao il mondo", filters={"a": "b"}
            )

            assert len(dashboard_json["tiles"]) == 2
            tile_ids = sorted([tile["id"] for tile in dashboard_json["tiles"]])

            frozen_time.tick(delta=datetime.timedelta(hours=10))
            other_user = User.objects.create_and_join(organization=self.organization, email="", password="")
            self.client.force_login(other_user)
            updated_tile = {**dashboard_json["tiles"][0]}
            updated_tile["saved_filter"]["name"] = "anche ciao"
            dashboard_id, dashboard_json = self.dashboard_api.update_dashboard_tile(dashboard_id, updated_tile)

            sorted_tiles = sorted(dashboard_json["tiles"], key=lambda x: x["id"])
            assert len(sorted_tiles) == 2

            assert sorted_tiles[0]["id"] == tile_ids[0]
            assert sorted_tiles[1]["id"] == tile_ids[1]

            # the edit to tile 0 has changed the text
            assert sorted_tiles[0]["saved_filter"]["name"] == "anche ciao"
            assert sorted_tiles[1]["saved_filter"]["name"] == "ciao il mondo"

            # created by is set for both tiles
            assert sorted_tiles[0]["saved_filter"]["created_by"]["id"] == self.user.id
            assert sorted_tiles[1]["saved_filter"]["created_by"]["id"] == self.user.id

            # tile 1 has never been modified so has no modified by user
            assert sorted_tiles[0]["saved_filter"]["last_modified_by"]["id"] == other_user.id
            assert sorted_tiles[1]["saved_filter"]["last_modified_by"] is None

            # tile 1 has not been modified, but tile 0 has. Tile 0 has a new modified at date
            assert sorted_tiles[0]["saved_filter"]["last_modified_at"] == "2022-04-01T22:45:00Z"
            assert sorted_tiles[1]["saved_filter"]["last_modified_at"] == "2022-04-01T12:45:00Z"

    def test_can_update_a_single_saved_filter_tile_color(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard"})

        dashboard_id, dashboard_json = self.dashboard_api.create_saved_filter_tile(
            dashboard_id, name="hello world", filters={"a": "b"}
        )
        dashboard_id, dashboard_json = self.dashboard_api.create_saved_filter_tile(
            dashboard_id, name="ciao il mondo", filters={"a": "b"}
        )

        assert len(dashboard_json["tiles"]) == 2
        tile_ids = [tile["id"] for tile in dashboard_json["tiles"]]

        updated_tile = {**dashboard_json["tiles"][0]}
        updated_tile["color"] = "purple"
        dashboard_id, dashboard_json = self.dashboard_api.update_dashboard_tile(dashboard_id, updated_tile)

        assert len(dashboard_json["tiles"]) == 2
        assert [(t["id"], t["color"]) for t in dashboard_json["tiles"]] == [
            (tile_ids[0], "purple"),
            (tile_ids[1], None),
        ]

    def test_can_remove_saved_filter_tiles_from_dashboard(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard"})

        dashboard_id, dashboard_json = self.dashboard_api.create_saved_filter_tile(dashboard_id, name="io sono testo")
        dashboard_id, dashboard_json = self.dashboard_api.create_saved_filter_tile(dashboard_id, name="soy texto")
        dashboard_id, dashboard_json = self.dashboard_api.create_saved_filter_tile(dashboard_id, name="i am text")
        dashboard_id, dashboard_json = self.dashboard_api.create_saved_filter_tile(dashboard_id, name="ich bin text")

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
        assert [t["saved_filter"]["name"] for t in tiles] == ["io sono testo", "soy texto", "i am text"]

    def test_do_not_see_deleted_saved_filter_tiles_when_adding_new_ones(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard"})

        self.dashboard_api.create_saved_filter_tile(dashboard_id, name="io sono testo")
        dashboard_id, dashboard_json = self.dashboard_api.create_saved_filter_tile(dashboard_id, name="soy texto")

        assert len(dashboard_json["tiles"]) == 2

        self.dashboard_api.update_dashboard_tile(dashboard_id, {**dashboard_json["tiles"][0], "deleted": True})

        dashboard_json = self.dashboard_api.get_dashboard(dashboard_id)
        assert len(dashboard_json["tiles"]) == 1

        _, with_another_tile_dashboard_json = self.dashboard_api.create_saved_filter_tile(
            dashboard_id, name="i am a third text"
        )
        assert len(with_another_tile_dashboard_json["tiles"]) == 2
        assert [t["saved_filter"]["name"] for t in with_another_tile_dashboard_json["tiles"]] == [
            "soy texto",
            "i am a third text",
        ]
