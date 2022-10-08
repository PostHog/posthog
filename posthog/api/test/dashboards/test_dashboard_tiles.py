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
    def test_can_create_a_single_text_tile(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard"})

        dashboard_id, dashboard_json = self.dashboard_api.create_text_tile(dashboard_id, text="hello world")

        assert len(dashboard_json["tiles"]) == 1
        assert dashboard_json["tiles"][0] == self._expected_tile_with_text(
            body="hello world",
        )

    @freeze_time("2022-04-01 12:45")
    def test_can_update_a_single_text_tile(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard"})

        dashboard_id, dashboard_json = self.dashboard_api.create_text_tile(dashboard_id, text="hello world")
        dashboard_id, dashboard_json = self.dashboard_api.create_text_tile(dashboard_id, text="ciao il mondo")

        assert len(dashboard_json["tiles"]) == 2
        tile_ids = [tile["id"] for tile in dashboard_json["tiles"]]

        updated_tile = {**dashboard_json["tiles"][0]}
        updated_tile["text"]["body"] = "anche ciao"
        dashboard_id, dashboard_json = self.dashboard_api.update_text_tile(dashboard_id, updated_tile)

        assert len(dashboard_json["tiles"]) == 2
        assert [(t["id"], t["text"]["body"]) for t in dashboard_json["tiles"]] == [
            (tile_ids[0], "anche ciao"),
            (tile_ids[1], "ciao il mondo"),
        ]

    @freeze_time("2022-04-01 12:45")
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
        assert [(t["id"], t["color"]) for t in dashboard_json["tiles"]] == [
            (tile_ids[0], "purple"),
            (tile_ids[1], None),
        ]

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
        assert [t["text"]["body"] for t in tiles] == ["io sono testo", "soy texto", "i am text"]
