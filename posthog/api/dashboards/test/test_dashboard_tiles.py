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
