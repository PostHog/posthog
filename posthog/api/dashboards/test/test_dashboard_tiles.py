from typing import Dict, List, Optional
from unittest import mock

from rest_framework import status

from posthog.api.test.dashboards import DashboardAPI
from posthog.models import DashboardTile, Team
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, QueryMatchingTest


class TestDashboardTiles(ClickhouseTestMixin, APIBaseTest, QueryMatchingTest):
    maxDiff = None

    def setUp(self) -> None:
        super().setUp()
        self.dashboard_api = DashboardAPI(self.client, self.team, self.assertEqual)
        self.another_team = Team.objects.create(organization=self.organization, name="other team")

        self.insight_id, self.insight_json = self.dashboard_api.create_insight({"name": "the insight"})
        self.dashboard_id, self.dashboard_json = self.dashboard_api.create_dashboard({"name": "the dashboard"})

    def test_can_add_an_insight_to_a_dashboard_as_an_isolated_operation(self) -> None:
        # repeat the same API call
        self.dashboard_api.add_insight_to_dashboard([self.dashboard_id], self.insight_id)
        self.dashboard_api.add_insight_to_dashboard([self.dashboard_id], self.insight_id)

        tiles_count = DashboardTile.objects.filter(insight_id=self.insight_id, dashboard_id=self.dashboard_id).count()
        assert tiles_count == 1

        tile: DashboardTile = DashboardTile.objects.get(insight_id=self.insight_id, dashboard_id=self.dashboard_id)
        tile.deleted = True
        tile.layouts = {"is set": "to some value"}
        tile.save()

        # adding when there is an existing soft-deleted tile, undeletes the tile
        self.dashboard_api.add_insight_to_dashboard([self.dashboard_id], self.insight_id)

        insight_json = self.dashboard_api.get_insight(self.insight_id)
        assert insight_json["dashboards"] == [self.dashboard_id]

        # adding to a deleted relation undeletes the tile
        tile.refresh_from_db()
        assert tile.deleted is False
        assert tile.layouts == {"is set": "to some value"}

    def test_can_remove_an_insight_from_a_dashboard_as_an_isolated_operation(self) -> None:
        self.dashboard_api.add_insight_to_dashboard([self.dashboard_id], self.insight_id)

        self.dashboard_api.remove_insight_from_dashboard(self.dashboard_id, self.insight_id)

        insight_json = self.dashboard_api.get_insight(self.insight_id)
        assert insight_json["dashboards"] == []
        dashboard_json = self.dashboard_api.get_dashboard(self.dashboard_id)
        assert dashboard_json["tiles"] == []

        self.dashboard_api.remove_insight_from_dashboard(self.dashboard_id, self.insight_id)

        tiles = DashboardTile.objects.filter(insight_id=self.insight_id, dashboard_id=self.dashboard_id)
        assert tiles.count() == 1
        assert tiles[0].deleted is True

        tile: DashboardTile = DashboardTile.objects.get(insight_id=self.insight_id, dashboard_id=self.dashboard_id)
        tile.deleted = False
        tile.layouts = {"some": "layouts"}
        tile.save()

        self.dashboard_api.remove_insight_from_dashboard(self.dashboard_id, self.insight_id)
        response_json = self.dashboard_api.get_insight(self.insight_id)
        assert response_json["dashboards"] == []

        # adding to a deleted relation re-deletes the same tile
        tile.refresh_from_db()
        assert tile.deleted is True
        assert tile.layouts == {"some": "layouts"}

    def test_changes_update_the_activity_log(self) -> None:
        self.dashboard_api.add_insight_to_dashboard([self.dashboard_id], self.insight_id)
        self.dashboard_api.remove_insight_from_dashboard(self.dashboard_id, self.insight_id)

        self.assert_insight_activity(
            self.insight_id,
            [
                self._an_insight_activity_log(
                    activity="updated",
                    before=[
                        {
                            "dashboard": {"id": self.dashboard_id, "name": self.dashboard_json["name"]},
                            "insight": {"id": self.insight_id},
                        }
                    ],
                    after=[],
                ),
                self._an_insight_activity_log(
                    activity="updated",
                    before=[],
                    after=[
                        {
                            "dashboard": {"id": self.dashboard_id, "name": self.dashboard_json["name"]},
                            "insight": {"id": self.insight_id},
                        }
                    ],
                ),
                self._an_insight_activity_log(
                    activity="created",
                    before=None,
                    after=None,
                ),
            ],
        )

    def test_must_provide_insight(self) -> None:
        create_response = self.client.post(
            f"/api/projects/{self.team.id}/dashboard_tiles",
            {"dashboard": 1},
        )
        self.assertEqual(create_response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_must_provide_insight_that_exists(self) -> None:
        create_response = self.client.post(
            f"/api/projects/{self.team.id}/dashboard_tiles",
            {"dashboard": self.dashboard_id, "insight": 200},
        )
        self.assertEqual(create_response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_must_provide_dashboard(self) -> None:
        create_response = self.client.post(
            f"/api/projects/{self.team.id}/dashboard_tiles",
            {"insight": self.insight_id, "dashboard": 200},
        )
        self.assertEqual(create_response.status_code, status.HTTP_400_BAD_REQUEST)

    def _an_insight_activity_log(
        self, activity: str, before: Optional[List[Dict]], after: Optional[List[Dict]]
    ) -> Dict:
        return {
            "activity": activity,
            "created_at": mock.ANY,
            "detail": {
                "changes": None
                if before is None and after is None
                else [
                    {
                        "action": "changed",
                        "after": after,
                        "before": before,
                        "field": "dashboards",
                        "type": "Insight",
                    }
                ],
                "name": self.insight_json["name"],
                "short_id": self.insight_json["short_id"],
                "trigger": None,
            },
            "item_id": str(self.insight_id),
            "scope": "Insight",
            "user": {"email": "user1@posthog.com", "first_name": ""},
        }

    def assert_insight_activity(self, insight_id: Optional[int], expected: List[Dict]):
        activity_response = self.dashboard_api.get_insight_activity(insight_id)

        activity: List[Dict] = activity_response["results"]

        self.maxDiff = None
        self.assertEqual(activity, expected)
