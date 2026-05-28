from posthog.test.base import APIBaseTest

from django.test import override_settings

from parameterized import parameterized
from rest_framework import status

from posthog.api.test.dashboards import DashboardAPI
from posthog.constants import AvailableFeature
from posthog.models import User

from products.dashboards.backend.models.dashboard_tile import DashboardTile


@override_settings(IN_UNIT_TESTING=True)
class TestDashboardDeleteTile(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        # restriction_level enforcement requires the ACCESS_CONTROL product feature on the org.
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
        ]
        self.organization.save()
        self.dashboard_api = DashboardAPI(self.client, self.team, self.assertEqual)

    def _delete_tile(self, dashboard_id: int, tile_id: int, expected_status: int = status.HTTP_204_NO_CONTENT):
        response = self.client.post(
            f"/api/projects/{self.team.id}/dashboards/{dashboard_id}/delete_tile",
            {"tile_id": tile_id},
        )
        self.assertEqual(response.status_code, expected_status, response.content)
        return response

    def test_can_delete_a_text_tile(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard"})
        _, dashboard_json = self.dashboard_api.create_text_tile(dashboard_id, text="hello world")
        _, dashboard_json = self.dashboard_api.create_text_tile(dashboard_id, text="second tile")

        tile_to_delete = dashboard_json["tiles"][0]
        self._delete_tile(dashboard_id, tile_to_delete["id"])

        remaining = self.dashboard_api.get_dashboard(dashboard_id)["tiles"]
        assert len(remaining) == 1
        assert remaining[0]["id"] != tile_to_delete["id"]

        # The text record itself is preserved — only the tile row is soft-deleted.
        tile = DashboardTile.objects_including_soft_deleted.get(id=tile_to_delete["id"])
        assert tile.deleted is True
        assert tile.text is not None

    def test_can_delete_an_insight_tile_without_deleting_the_insight(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard"})
        insight_id, _ = self.dashboard_api.create_insight({"name": "insight", "dashboards": [dashboard_id]})

        dashboard_json = self.dashboard_api.get_dashboard(dashboard_id)
        assert len(dashboard_json["tiles"]) == 1
        tile_id = dashboard_json["tiles"][0]["id"]

        self._delete_tile(dashboard_id, tile_id)

        # Tile is gone from the dashboard but the underlying insight still exists.
        assert self.dashboard_api.get_dashboard(dashboard_id)["tiles"] == []
        insight_response = self.client.get(f"/api/projects/{self.team.id}/insights/{insight_id}")
        assert insight_response.status_code == status.HTTP_200_OK

    def _setup_unknown_tile_id(self) -> tuple[int, int]:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard"})
        return dashboard_id, 9_999_999

    def _setup_tile_from_other_dashboard(self) -> tuple[int, int]:
        dashboard_a, _ = self.dashboard_api.create_dashboard({"name": "a"})
        dashboard_b, _ = self.dashboard_api.create_dashboard({"name": "b"})
        _, dashboard_json = self.dashboard_api.create_text_tile(dashboard_a, text="on a")
        tile_id = dashboard_json["tiles"][0]["id"]
        return dashboard_b, tile_id

    def _setup_parent_dashboard_soft_deleted(self) -> tuple[int, int]:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard"})
        _, dashboard_json = self.dashboard_api.create_text_tile(dashboard_id, text="hi")
        tile_id = dashboard_json["tiles"][0]["id"]
        self.client.patch(f"/api/projects/{self.team.id}/dashboards/{dashboard_id}", {"deleted": True})
        return dashboard_id, tile_id

    def _setup_tile_already_soft_deleted(self) -> tuple[int, int]:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard"})
        _, dashboard_json = self.dashboard_api.create_text_tile(dashboard_id, text="hi")
        tile_id = dashboard_json["tiles"][0]["id"]
        self._delete_tile(dashboard_id, tile_id)
        return dashboard_id, tile_id

    @parameterized.expand(
        [
            ("unknown_tile_id", _setup_unknown_tile_id),
            ("tile_belongs_to_other_dashboard", _setup_tile_from_other_dashboard),
            ("parent_dashboard_soft_deleted", _setup_parent_dashboard_soft_deleted),
            ("tile_already_soft_deleted", _setup_tile_already_soft_deleted),
        ]
    )
    def test_delete_returns_404(self, _name, setup) -> None:
        dashboard_id, tile_id = setup(self)
        self._delete_tile(dashboard_id, tile_id, expected_status=status.HTTP_404_NOT_FOUND)

    def test_delete_tile_requires_tile_id(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard"})
        response = self.client.post(f"/api/projects/{self.team.id}/dashboards/{dashboard_id}/delete_tile", {})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_delete_tile_requires_edit_permission(self) -> None:
        dashboard_id, dashboard_json = self.dashboard_api.create_dashboard(
            {"name": "dashboard", "restriction_level": 37},  # only collaborators can edit
        )
        _, with_tile = self.dashboard_api.create_text_tile(dashboard_id, text="hi")
        tile_id = with_tile["tiles"][0]["id"]

        other_user = User.objects.create_and_join(self.organization, "other@example.com", "password")
        self.client.force_login(other_user)

        self._delete_tile(dashboard_id, tile_id, expected_status=status.HTTP_403_FORBIDDEN)
