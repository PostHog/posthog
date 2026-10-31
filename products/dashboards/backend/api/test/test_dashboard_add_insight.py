from posthog.test.base import APIBaseTest
from unittest.mock import ANY, MagicMock, patch

from parameterized import parameterized
from rest_framework import status

from posthog.api.test.dashboards import DashboardAPI
from posthog.constants import AvailableFeature
from posthog.models.organization import Organization, OrganizationMembership

from products.access_control.backend.models.access_control import AccessControl
from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.models.dashboard_tile import DashboardTile
from products.product_analytics.backend.facade.models import Insight


class TestDashboardAddInsight(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.dashboard_api = DashboardAPI(self.client, self.team, self.assertEqual)
        self.dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "Growth overview"})
        self.insight_id, _ = self.dashboard_api.create_insight({"name": "Weekly signups"})

    def _add_insight(self, insight_id: int, expected_status: int = status.HTTP_200_OK) -> dict:
        response = self.client.post(
            f"/api/projects/{self.team.id}/dashboards/{self.dashboard_id}/add_insight/",
            {"insight_id": insight_id},
        )
        assert response.status_code == expected_status, response.content
        return response.json()

    def _tiles_for_insight(self, insight_id: int) -> list[DashboardTile]:
        return list(
            DashboardTile.objects_including_soft_deleted.filter(dashboard_id=self.dashboard_id, insight_id=insight_id)
        )

    @patch("products.dashboards.backend.api.dashboard.report_user_action")
    def test_places_the_insight_on_the_dashboard(self, mock_report_user_action: MagicMock) -> None:
        tile_json = self._add_insight(self.insight_id)

        assert tile_json == {"id": ANY, "dashboard_id": self.dashboard_id, "deleted": None}
        dashboard_json = self.dashboard_api.get_dashboard(self.dashboard_id)
        assert [(tile["id"], tile["insight"]["id"]) for tile in dashboard_json["tiles"]] == [
            (tile_json["id"], self.insight_id)
        ]
        mock_report_user_action.assert_any_call(
            self.user,
            "dashboard tile added",
            {"tile_type": "insight", "insight_type": "trends", "dashboard_id": self.dashboard_id},
            team=ANY,
            request=ANY,
        )

    @parameterized.expand([("already_on_the_dashboard", False), ("removed_from_the_dashboard", True)])
    def test_adding_again_keeps_the_one_tile(self, _name: str, remove_first: bool) -> None:
        first_tile_id = self._add_insight(self.insight_id)["id"]
        if remove_first:
            response = self.client.post(
                f"/api/projects/{self.team.id}/dashboards/{self.dashboard_id}/delete_tile/",
                {"tile_id": first_tile_id},
            )
            assert response.status_code == status.HTTP_204_NO_CONTENT, response.content

        second_tile_id = self._add_insight(self.insight_id)["id"]

        assert second_tile_id == first_tile_id
        assert [(tile.id, bool(tile.deleted)) for tile in self._tiles_for_insight(self.insight_id)] == [
            (first_tile_id, False)
        ]

    @patch("posthog.resource_limits.evaluator.get_limit", return_value=1)
    @patch("posthog.resource_limits.evaluator.report_user_action")
    def test_reports_the_insight_limit_only_when_a_tile_is_added(
        self, mock_report_user_action: MagicMock, _mock_get_limit: MagicMock
    ) -> None:
        self._add_insight(self.insight_id)
        self._add_insight(self.insight_id)

        limit_hits = [call for call in mock_report_user_action.call_args_list if call.args[1] == "resource limit hit"]
        assert [
            (hit.args[2]["limit_key"], hit.args[2]["dashboard_id"], hit.args[2]["dashboard_name"]) for hit in limit_hits
        ] == [("analytics.max_insights_per_dashboard", self.dashboard_id, "Growth overview")]

    @parameterized.expand(
        [
            ("dashboard_is_view_only", "dashboard", "viewer", False),
            ("insight_is_hidden", "insight", "none", False),
            ("insight_is_hidden_in_a_sibling_environment", "insight", "none", True),
        ]
    )
    def test_refuses_a_member_who_cannot_edit_the_dashboard_or_view_the_insight(
        self, _name: str, resource: str, access_level: str, in_sibling_environment: bool
    ) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
        ]
        self.organization.save()
        team = self.team
        if in_sibling_environment:
            team = self.create_sibling_environment()
            self.dashboard_id = Dashboard.objects.create(team=team, name="Growth overview").id
            self.insight_id = Insight.objects.create(team=team, name="Weekly signups").id
        resource_id = self.dashboard_id if resource == "dashboard" else self.insight_id
        AccessControl.objects.create(
            team=team, resource=resource, resource_id=str(resource_id), access_level=access_level
        )
        member = self._create_user("member@example.com", level=OrganizationMembership.Level.MEMBER)
        self.client.force_login(member)

        self._add_insight(self.insight_id, expected_status=status.HTTP_403_FORBIDDEN)

        assert self._tiles_for_insight(self.insight_id) == []

    @parameterized.expand([("another_organization",), ("sibling_environment",)])
    def test_refuses_an_insight_from_another_team(self, owner: str) -> None:
        if owner == "another_organization":
            _, _, other_team = Organization.objects.bootstrap(None, name="Other org")
        else:
            other_team = self.create_sibling_environment()
        other_insight = Insight.objects.create(team=other_team, name="Elsewhere")

        self._add_insight(other_insight.id, expected_status=status.HTTP_404_NOT_FOUND)

        assert self._tiles_for_insight(other_insight.id) == []
