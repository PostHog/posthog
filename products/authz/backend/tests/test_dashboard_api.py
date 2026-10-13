from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.dashboards.backend.models.dashboard import Dashboard


class TestDashboardAuthorizationAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.dashboard = Dashboard.objects.create(team=self.team, name="Authorization test", created_by=self.user)
        self.other_dashboard = Dashboard.objects.create(team=self.team, name="Other dashboard", created_by=self.user)
        self.allowed_relations = {"can_view", "can_edit", "can_delete", "can_manage_access", "can_share"}
        self.allow_resource = True
        self.listed_ids = [self.dashboard.pk]
        self.client_fga = MagicMock()
        self.client_fga.client_batch_check.side_effect = lambda checks, options: [
            MagicMock(
                allowed=self.allow_resource
                if check.object.startswith("resource:")
                else check.relation in self.allowed_relations,
                error=None,
            )
            for check in checks
        ]
        self.client_fga.streamed_list_objects.side_effect = self.list_objects
        for patcher in (
            patch("products.authz.backend.logic.rollout.get_feature_flag_or_none", return_value="v2"),
            patch("products.authz.backend.logic.authorization.ready_state", return_value=b"ready:test"),
            patch("products.authz.backend.logic.authorization.get_openfga_client", return_value=self.client_fga),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def list_objects(self, request, options) -> MagicMock:
        stream = MagicMock()
        stream.__iter__.return_value = iter(
            MagicMock(object=f"dashboard:{self.organization.pk}/{self.team.pk}/{id}") for id in self.listed_ids
        )
        return stream

    @parameterized.expand(
        [
            ("retrieve", "get", "", {}, "can_view"),
            ("update", "patch", "", {"name": "Changed"}, "can_edit"),
            ("tile_mutation", "post", "create_text_tile", {"text": "Example"}, "can_edit"),
            ("access_controls", "put", "access_controls", {"access_level": "viewer"}, "can_manage_access"),
            ("sharing", "get", "sharing", {}, "can_view"),
            ("sharing_mutation", "patch", "sharing", {"enabled": True}, "can_share"),
        ]
    )
    def test_v2_denial_is_enforced_across_dashboard_routes(
        self, _name: str, method: str, action: str, data: dict, denied_relation: str
    ) -> None:
        self.allowed_relations.remove(denied_relation)
        url = f"/api/projects/{self.team.pk}/dashboards/{self.dashboard.pk}/{action}"
        response = getattr(self.client, method)(url, data, format="json")
        assert response.status_code == 403, response.data
        self.dashboard.refresh_from_db()
        assert self.dashboard.name == "Authorization test"

    def test_manage_access_does_not_require_dashboard_edit_access(self) -> None:
        self.allowed_relations = {"can_manage_access"}
        response = self.client.put(
            f"/api/projects/{self.team.pk}/dashboards/{self.dashboard.pk}/access_controls/",
            {"access_level": "viewer"},
            format="json",
        )
        assert response.status_code == 200, response.data
        assert response.data["access_level"] == "viewer"

    def test_resource_denial_prevents_creation(self) -> None:
        self.allow_resource = False
        response = self.client.post(f"/api/projects/{self.team.pk}/dashboards/", {"name": "Denied"})
        assert response.status_code == 403, response.data
        assert not Dashboard.objects.filter(team=self.team, name="Denied").exists()

    def test_source_view_denial_prevents_duplication(self) -> None:
        self.allowed_relations.remove("can_view")
        response = self.client.post(
            f"/api/projects/{self.team.pk}/dashboards/", {"use_dashboard": self.dashboard.pk}, format="json"
        )
        assert response.status_code == 403, response.data
        assert Dashboard.objects.filter(team=self.team).count() == 2

    def test_authorized_restore_uses_the_dashboard_policy(self) -> None:
        self.allow_resource = False
        self.dashboard.deleted = True
        self.dashboard.save()
        response = self.client.patch(
            f"/api/projects/{self.team.pk}/dashboards/{self.dashboard.pk}/", {"deleted": False}, format="json"
        )
        assert response.status_code == 200, response.data
        self.dashboard.refresh_from_db()
        assert not self.dashboard.deleted

    def test_list_and_serializer_use_v2_permissions(self) -> None:
        self.allowed_relations = {"can_view", "can_manage_access"}
        self.other_dashboard.deleted = True
        self.other_dashboard.save()
        self.listed_ids.append(self.other_dashboard.pk)
        response = self.client.get(f"/api/projects/{self.team.pk}/dashboards/")
        assert response.status_code == 200, response.data
        assert [item["id"] for item in response.data["results"]] == [self.dashboard.pk]
        assert response.data["results"][0]["user_access_level"] == "viewer"
        assert response.data["results"][0]["effective_privilege_level"] == Dashboard.PrivilegeLevel.CAN_VIEW

    def test_search_filters_dashboards_and_reports_v2_access(self) -> None:
        self.allowed_relations = {"can_view"}
        response = self.client.get(f"/api/projects/{self.team.pk}/search/", {"entities": "dashboard"})
        assert response.status_code == 200, response.data
        assert [item["result_id"] for item in response.data["results"]] == [str(self.dashboard.pk)]
        assert response.data["results"][0]["user_access_level"] == "viewer"

    def test_incomplete_listing_fails_closed(self) -> None:
        with patch("products.authz.backend.logic.authorization.ready_state", return_value=None):
            response = self.client.get(f"/api/projects/{self.team.pk}/dashboards/")
        assert response.status_code == 403, response.data

    def test_bulk_tag_update_does_not_bypass_v2(self) -> None:
        self.allowed_relations = {"can_view", "can_manage_access"}
        response = self.client.post(
            f"/api/projects/{self.team.pk}/dashboards/bulk_update_tags/",
            {"ids": [self.dashboard.pk], "tags": ["example"], "action": "add"},
            format="json",
        )
        assert response.status_code == 200, response.data
        assert response.data["updated"] == []
        assert response.data["skipped"][0]["id"] == self.dashboard.pk
