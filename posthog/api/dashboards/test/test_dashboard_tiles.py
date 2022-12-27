from datetime import timedelta
from typing import Dict, List, Optional
from unittest import mock

from freezegun import freeze_time

from posthog.api.test.dashboards import DashboardAPI
from posthog.models import DashboardTile, Team
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, QueryMatchingTest


class TestDashboardTiles(ClickhouseTestMixin, APIBaseTest, QueryMatchingTest):
    maxDiff = None

    def setUp(self) -> None:
        super().setUp()
        self.dashboard_api = DashboardAPI(self.client, self.team, self.assertEqual)
        self.another_team = Team.objects.create(organization=self.organization, name="other team")

    def test_can_add_an_insight_to_a_dashboard_as_an_isolated_operation(self) -> None:
        insight_id, _ = self.dashboard_api.create_insight({})
        dashboard_id, _ = self.dashboard_api.create_dashboard({})
        # repeat the same API call
        self.dashboard_api.add_insight_to_dashboard([dashboard_id], insight_id)
        self.dashboard_api.add_insight_to_dashboard([dashboard_id], insight_id)

        tiles_count = DashboardTile.objects.filter(insight_id=insight_id, dashboard_id=dashboard_id).count()
        assert tiles_count == 1

        tile: DashboardTile = DashboardTile.objects.get(insight_id=insight_id, dashboard_id=dashboard_id)
        tile.deleted = True
        tile.layouts = {"is set": "to some value"}
        tile.save()

        # adding when there is an existing soft-deleted tile, undeletes the tile
        self.dashboard_api.add_insight_to_dashboard([dashboard_id], insight_id)

        insight_json = self.dashboard_api.get_insight(insight_id)
        assert insight_json["dashboards"] == [dashboard_id]

        # adding to a deleted relation undeletes the tile
        tile.refresh_from_db()
        assert tile.deleted is False
        assert tile.layouts == {"is set": "to some value"}

    def test_can_remove_an_insight_from_a_dashboard_as_an_isolated_operation(self) -> None:
        insight_id, _ = self.dashboard_api.create_insight({})
        dashboard_id, _ = self.dashboard_api.create_dashboard({})
        self.dashboard_api.add_insight_to_dashboard([dashboard_id], insight_id)

        self.dashboard_api.remove_insight_from_dashboard(dashboard_id, insight_id)

        insight_json = self.dashboard_api.get_insight(insight_id)
        assert insight_json["dashboards"] == []
        dashboard_json = self.dashboard_api.get_dashboard(dashboard_id)
        assert dashboard_json["tiles"] == []

        self.dashboard_api.remove_insight_from_dashboard(dashboard_id, insight_id)

        tiles = DashboardTile.objects.filter(insight_id=insight_id, dashboard_id=dashboard_id)
        assert tiles.count() == 1
        assert tiles[0].deleted is True

        tile: DashboardTile = DashboardTile.objects.get(insight_id=insight_id, dashboard_id=dashboard_id)
        tile.deleted = False
        tile.layouts = {"some": "layouts"}
        tile.save()

        self.dashboard_api.remove_insight_from_dashboard(dashboard_id, insight_id)
        response_json = self.dashboard_api.get_insight(insight_id)
        assert response_json["dashboards"] == []

        # adding to a deleted relation re-deletes the same tile
        tile.refresh_from_db()
        assert tile.deleted is True
        assert tile.layouts == {"some": "layouts"}

    def test_changes_update_the_activity_log(self) -> None:
        with freeze_time("2012-01-14T03:21:34.000Z") as frozen_time:
            insight_id, insight_json = self.dashboard_api.create_insight({"name": "the insight"})
            dashboard_id, _ = self.dashboard_api.create_dashboard({})

            frozen_time.tick(timedelta(seconds=1))
            self.dashboard_api.add_insight_to_dashboard([dashboard_id], insight_id)

            frozen_time.tick(timedelta(seconds=1))
            self.dashboard_api.remove_insight_from_dashboard(dashboard_id, insight_id)

        self.assert_insight_activity(
            insight_id,
            [
                self._an_insight_activity_log(
                    activity="updated",
                    insight_id=insight_id,
                    insight_short_id=insight_json["short_id"],
                    before=[{"dashboard": {"id": dashboard_id, "name": None}, "insight": {"id": insight_id}}],
                    after=[],
                ),
                self._an_insight_activity_log(
                    activity="updated",
                    insight_id=insight_id,
                    insight_short_id=insight_json["short_id"],
                    before=[],
                    after=[{"dashboard": {"id": dashboard_id, "name": None}, "insight": {"id": insight_id}}],
                ),
                self._an_insight_activity_log(
                    activity="created",
                    insight_id=insight_id,
                    insight_short_id=insight_json["short_id"],
                    before=None,
                    after=None,
                ),
            ],
        )

    @staticmethod
    def _an_insight_activity_log(
        activity: str, insight_id: int, insight_short_id: str, before: Optional[List[Dict]], after: Optional[List[Dict]]
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
                "name": "the insight",
                "short_id": insight_short_id,
                "trigger": None,
            },
            "item_id": str(insight_id),
            "scope": "Insight",
            "user": {"email": "user1@posthog.com", "first_name": ""},
        }

    def assert_insight_activity(self, insight_id: Optional[int], expected: List[Dict]):
        activity_response = self.dashboard_api.get_insight_activity(insight_id)

        activity: List[Dict] = activity_response["results"]

        self.maxDiff = None
        self.assertEqual(activity, expected)
