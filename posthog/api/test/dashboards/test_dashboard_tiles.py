from typing import Dict, Optional, Union
from unittest import mock

from freezegun import freeze_time

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

        tile_id, tile_json = self.dashboard_api.create_text_tile(dashboard_id, text="hello world")

        assert tile_json == self._expected_tile_with_text(
            dashboard_id=dashboard_id,
            body="hello world",
        )
