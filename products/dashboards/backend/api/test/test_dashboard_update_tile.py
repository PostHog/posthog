from posthog.test.base import APIBaseTest

from parameterized import parameterized
from rest_framework import status

from posthog.schema import DateRange, EventsNode, InsightVizNode, TrendsFilter, TrendsQuery

from posthog.api.test.dashboards import DashboardAPI
from posthog.models.organization import Organization
from posthog.models.team import Team

from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.models.dashboard_tile import DashboardTile, Text
from products.dashboards.backend.models.dashboard_widget import DashboardWidget


def _trends_query_dict(event: str = "$pageview") -> dict:
    return InsightVizNode(
        source=TrendsQuery(
            series=[EventsNode(event=event)],
            dateRange=DateRange(date_from="-7d"),
            trendsFilter=TrendsFilter(display="ActionsLineGraph"),
        ),
    ).model_dump()


class TestDashboardUpdateTile(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.dashboard_api = DashboardAPI(self.client, self.team, self.assertEqual)

    def _make_tile(self, kind: str) -> tuple[int, int]:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dash"})
        if kind == "insight":
            insight_id, _ = self.dashboard_api.create_insight(
                {"name": "A", "query": _trends_query_dict(), "dashboards": [dashboard_id]}
            )
            tile = DashboardTile.objects.get(dashboard_id=dashboard_id, insight_id=insight_id)
        else:
            widget = DashboardWidget.all_teams.create(
                team=self.team, widget_type="error_tracking_list", config={"limit": 10}
            )
            tile = DashboardTile.objects.create(dashboard_id=dashboard_id, widget=widget)
        return dashboard_id, tile.id

    def _update(self, dashboard_id: int, payload: dict, expected_status: int = status.HTTP_200_OK) -> dict:
        response = self.client.post(
            f"/api/projects/{self.team.id}/dashboards/{dashboard_id}/update_tile/",
            payload,
        )
        assert response.status_code == expected_status, response.content
        return response.json()

    @parameterized.expand(
        [
            ("insight_hide", "insight", False),
            ("insight_show", "insight", True),
            ("widget_hide", "widget", False),
            ("widget_show", "widget", True),
        ]
    )
    def test_sets_show_description(self, _name: str, kind: str, value: bool) -> None:
        dashboard_id, tile_id = self._make_tile(kind)

        body = self._update(dashboard_id, {"tile_id": tile_id, "show_description": value})

        assert body["show_description"] == value
        assert DashboardTile.objects.get(id=tile_id).show_description == value

    def test_sets_color(self) -> None:
        dashboard_id, tile_id = self._make_tile("insight")

        self._update(dashboard_id, {"tile_id": tile_id, "color": "blue"})

        assert DashboardTile.objects.get(id=tile_id).color == "blue"

    def test_sets_layouts(self) -> None:
        dashboard_id, tile_id = self._make_tile("insight")
        layouts = {"sm": {"x": 0, "y": 0, "w": 6, "h": 5}}

        self._update(dashboard_id, {"tile_id": tile_id, "layouts": layouts})

        assert DashboardTile.objects.get(id=tile_id).layouts == layouts

    def test_only_updates_provided_fields(self) -> None:
        dashboard_id, tile_id = self._make_tile("insight")
        DashboardTile.objects.filter(id=tile_id).update(color="green")

        self._update(dashboard_id, {"tile_id": tile_id, "show_description": False})

        tile = DashboardTile.objects.get(id=tile_id)
        assert tile.show_description is False
        assert tile.color == "green"

    def test_rejects_text_tile(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dash"})
        text = Text.objects.create(body="hi", team=self.team)
        tile = DashboardTile.objects.create(dashboard_id=dashboard_id, text=text)

        self._update(
            dashboard_id,
            {"tile_id": tile.id, "show_description": False},
            expected_status=status.HTTP_400_BAD_REQUEST,
        )

    def test_rejects_tile_from_other_dashboard(self) -> None:
        dashboard_id, _ = self._make_tile("insight")
        _, other_tile_id = self._make_tile("insight")

        self._update(
            dashboard_id,
            {"tile_id": other_tile_id, "show_description": False},
            expected_status=status.HTTP_404_NOT_FOUND,
        )

    def test_rejects_dashboard_from_other_team(self) -> None:
        other_team = Team.objects.create(organization=Organization.objects.create(name="other"), name="other")
        other_dashboard = Dashboard.objects.create(team=other_team, name="other")

        self._update(
            other_dashboard.id,
            {"tile_id": 1, "show_description": False},
            expected_status=status.HTTP_404_NOT_FOUND,
        )
