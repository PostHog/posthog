from urllib.parse import parse_qs, urlparse

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.team import Team
from posthog.models.user import User

from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.models.dashboard_saved_view import DashboardSavedView


class TestDashboardSavedViews(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.saved_views_flag = patch(
            "products.dashboards.backend.api.dashboard_saved_view.dashboard_saved_views_enabled", return_value=True
        )
        self.saved_views_flag.start()
        self.addCleanup(self.saved_views_flag.stop)
        self.base_url = f"/api/projects/{self.team.pk}/dashboard_saved_views/"

    def _payload(self, **overrides: object) -> dict[str, object]:
        payload: dict[str, object] = {
            "name": "Product dashboards",
            "filters": {"tags": ["product"], "shared": True},
        }
        payload.update(overrides)
        return payload

    @patch("products.dashboards.backend.api.dashboard_saved_view.dashboard_saved_views_enabled", return_value=False)
    def test_rejects_requests_when_saved_views_flag_is_disabled(self, _dashboard_saved_views_enabled) -> None:
        response = self.client.get(self.base_url)

        assert response.status_code == status.HTTP_403_FORBIDDEN

    @parameterized.expand(
        [
            ("without_filters", {}, "Add at least one filter before saving a view."),
            ("with_an_empty_creator_filter", {"createdBy": []}, "Add at least one filter before saving a view."),
            ("with_malformed_filters", {"tags": "product"}, "Tags must be a list of strings."),
            ("with_oversized_filters", {"search": "a" * 201}, "Search must be 200 characters or fewer."),
        ]
    )
    def test_rejects_saved_views_with_invalid_filters(self, _: str, filters: dict[str, object], detail: str) -> None:
        response = self.client.post(self.base_url, self._payload(filters=filters), format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["detail"] == detail

    def test_accepts_long_folder_paths(self) -> None:
        response = self.client.post(self.base_url, self._payload(filters={"folder": "a" * 201}), format="json")

        assert response.status_code == status.HTTP_201_CREATED, response.json()

    def test_rejects_saved_views_with_creators_outside_the_project(self) -> None:
        other_organization = Organization.objects.create(name="Other organization")
        other_user = User.objects.create_and_join(other_organization, "other@example.com", password="password")

        response = self.client.post(self.base_url, self._payload(filters={"createdBy": [other_user.id]}), format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["detail"] == "Creators must be active members of this project."

    @parameterized.expand(
        [
            ("personal", DashboardSavedView.Scope.PRIVATE, 50),
            ("team", DashboardSavedView.Scope.TEAM, 200),
        ]
    )
    def test_limits_saved_views_by_scope(self, _: str, scope: str, limit: int) -> None:
        DashboardSavedView.all_teams.bulk_create(
            [
                DashboardSavedView(
                    team=self.team,
                    name=f"Saved view {index}",
                    filters={"pinned": True},
                    scope=scope,
                    created_by=self.user,
                )
                for index in range(limit)
            ]
        )

        response = self.client.post(self.base_url, self._payload(scope=scope), format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["detail"] == f"You can save up to {limit} {scope} dashboard views."

    def test_rejects_updating_a_saved_view_without_filters(self) -> None:
        response = self.client.post(self.base_url, self._payload(), format="json")
        assert response.status_code == status.HTTP_201_CREATED, response.json()

        response = self.client.patch(f"{self.base_url}{response.json()['id']}/", {"filters": {}}, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["detail"] == "Add at least one filter before saving a view."

    def test_list_only_includes_saved_views_for_current_project(self) -> None:
        response = self.client.post(self.base_url, self._payload(), format="json")
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        assert response.json()["scope"] == "private"
        assert response.json()["can_change_scope"] is True

        other_team = Team.objects.create(organization=self.organization, name="Other project")
        DashboardSavedView.all_teams.create(
            team=other_team,
            name="Other project view",
            filters={},
            created_by=self.user,
        )

        response = self.client.get(self.base_url)

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert [view["name"] for view in response.json()["results"]] == ["Product dashboards"]
        assert response.json()["results"][0]["can_change_scope"] is True

    def test_list_uses_cursor_pagination(self) -> None:
        DashboardSavedView.all_teams.create(
            team=self.team,
            name="Alpha view",
            filters={"pinned": True},
            created_by=self.user,
        )
        DashboardSavedView.all_teams.create(
            team=self.team,
            name="Bravo view",
            filters={"shared": True},
            created_by=self.user,
        )
        DashboardSavedView.all_teams.create(
            team=self.team,
            name="Team view",
            filters={"shared": True},
            scope=DashboardSavedView.Scope.TEAM,
            created_by=self.user,
        )

        first_page = self.client.get(self.base_url, {"limit": "1", "scope": "private"})

        assert first_page.status_code == status.HTTP_200_OK, first_page.json()
        assert first_page.json()["next"] is not None
        assert [view["name"] for view in first_page.json()["results"]] == ["Alpha view"]
        cursor = parse_qs(urlparse(first_page.json()["next"]).query)["cursor"][0]
        second_page = self.client.get(
            self.base_url,
            {"limit": 1, "cursor": cursor, "scope": DashboardSavedView.Scope.PRIVATE},
        )
        assert second_page.status_code == status.HTTP_200_OK, second_page.json()
        assert [view["name"] for view in second_page.json()["results"]] == ["Bravo view"]

        team_page = self.client.get(self.base_url, {"scope": DashboardSavedView.Scope.TEAM})
        assert team_page.status_code == status.HTTP_200_OK, team_page.json()
        assert [view["name"] for view in team_page.json()["results"]] == ["Team view"]

    def test_child_environment_manages_parent_project_saved_views(self) -> None:
        child_team = Team.objects.create(
            organization=self.organization, parent_team=self.team, name="Child environment"
        )
        child_url = f"/api/projects/{child_team.pk}/dashboard_saved_views/"

        response = self.client.post(child_url, self._payload(), format="json")
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        saved_view_id = response.json()["id"]
        assert DashboardSavedView.all_teams.filter(id=saved_view_id, team=self.team).exists()

        response = self.client.get(child_url)

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert [view["name"] for view in response.json()["results"]] == ["Product dashboards"]

        response = self.client.patch(f"{child_url}{saved_view_id}/", {"name": "Updated view"}, format="json")
        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json()["name"] == "Updated view"

        response = self.client.delete(f"{child_url}{saved_view_id}/")
        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert not DashboardSavedView.all_teams.filter(id=saved_view_id).exists()

    @patch("products.dashboards.backend.api.dashboard_saved_view.UserAccessControl")
    def test_child_environment_authorizes_against_parent_project(self, user_access_control) -> None:
        user_access_control.return_value.check_access_level_for_resource.return_value = True
        child_team = Team.objects.create(
            organization=self.organization, parent_team=self.team, name="Child environment"
        )

        response = self.client.get(f"/api/projects/{child_team.pk}/dashboard_saved_views/")

        assert response.status_code == status.HTTP_200_OK, response.json()
        user_access_control.assert_called_once_with(user=self.user, team=self.team)

    def test_project_member_can_list_saved_views(self) -> None:
        response = self.client.post(self.base_url, self._payload(scope="team"), format="json")
        assert response.status_code == status.HTTP_201_CREATED, response.json()

        member = self._create_user("member@example.com", level=OrganizationMembership.Level.MEMBER)
        self.client.force_login(member)
        response = self.client.get(self.base_url)

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert [view["name"] for view in response.json()["results"]] == ["Product dashboards"]

    @patch(
        "products.dashboards.backend.api.dashboard_saved_view.UserAccessControl.check_access_level_for_resource",
        return_value=False,
    )
    def test_user_without_dashboard_viewer_access_cannot_list_saved_views(self, _check_access_level) -> None:
        response = self.client.get(self.base_url)

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_private_views_are_visible_only_to_their_creator(self) -> None:
        response = self.client.post(self.base_url, self._payload(scope="private"), format="json")
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        assert response.json()["scope"] == "private"

        member = self._create_user("member@example.com", level=OrganizationMembership.Level.MEMBER)
        self.client.force_login(member)
        response = self.client.get(self.base_url)

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json()["results"] == []

    def test_deleting_a_creator_removes_only_their_private_views(self) -> None:
        creator = self._create_user("creator@example.com", level=OrganizationMembership.Level.MEMBER)
        private_view = DashboardSavedView.all_teams.create(
            team=self.team,
            name="Private view",
            filters={"pinned": True},
            scope=DashboardSavedView.Scope.PRIVATE,
            created_by=creator,
        )
        team_view = DashboardSavedView.all_teams.create(
            team=self.team,
            name="Team view",
            filters={"pinned": True},
            scope=DashboardSavedView.Scope.TEAM,
            created_by=creator,
        )

        creator.delete()

        assert not DashboardSavedView.all_teams.filter(pk=private_view.id).exists()
        assert DashboardSavedView.all_teams.filter(pk=team_view.id, created_by__isnull=True).exists()

    @parameterized.expand(
        [
            ("create", "post", "", {"scope": "private"}),
            ("update", "patch", "{id}/", {"name": "Renamed view"}),
            ("delete", "delete", "{id}/", None),
        ]
    )
    @patch(
        "products.dashboards.backend.api.dashboard_saved_view.UserAccessControl.check_access_level_for_resource",
        return_value=False,
    )
    def test_read_only_user_cannot_mutate_saved_views(
        self, _action: str, method: str, path: str, data: dict[str, object] | None, _check_access_level
    ) -> None:
        saved_view = DashboardSavedView.all_teams.create(
            team=self.team,
            name="Private view",
            filters={},
            scope=DashboardSavedView.Scope.PRIVATE,
            created_by=self.user,
        )

        request = getattr(self.client, method)
        response = request(f"{self.base_url}{path.format(id=saved_view.id)}", data, format="json")

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert DashboardSavedView.all_teams.filter(pk=saved_view.id).exists()

    @patch(
        "products.dashboards.backend.api.dashboard_saved_view.UserAccessControl.check_access_level_for_resource",
        return_value=True,
    )
    def test_only_creator_can_change_a_team_view_visibility(self, _check_access_level) -> None:
        saved_view = DashboardSavedView.all_teams.create(
            team=self.team,
            name="Team view",
            filters={},
            scope=DashboardSavedView.Scope.TEAM,
            created_by=self.user,
        )
        member = self._create_user("member@example.com", level=OrganizationMembership.Level.MEMBER)
        self.client.force_login(member)

        response = self.client.patch(f"{self.base_url}{saved_view.id}/", {"scope": "private"}, format="json")

        assert response.status_code == status.HTTP_403_FORBIDDEN
        saved_view.refresh_from_db()
        assert saved_view.scope == DashboardSavedView.Scope.TEAM

    @patch(
        "products.dashboards.backend.api.dashboard_saved_view.UserAccessControl.check_access_level_for_resource",
        return_value=True,
    )
    def test_dashboard_editor_cannot_update_or_delete_another_users_private_view(self, _check_access_level) -> None:
        saved_view = DashboardSavedView.all_teams.create(
            team=self.team,
            name="Private view",
            filters={"pinned": True},
            scope=DashboardSavedView.Scope.PRIVATE,
            created_by=self.user,
        )
        member = self._create_user("member@example.com", level=OrganizationMembership.Level.MEMBER)
        self.client.force_login(member)

        update_response = self.client.patch(f"{self.base_url}{saved_view.id}/", {"name": "Renamed view"}, format="json")
        delete_response = self.client.delete(f"{self.base_url}{saved_view.id}/")

        assert update_response.status_code == status.HTTP_404_NOT_FOUND
        assert delete_response.status_code == status.HTTP_404_NOT_FOUND
        saved_view.refresh_from_db()
        assert saved_view.name == "Private view"

    @patch("products.dashboards.backend.api.dashboard_saved_view.report_user_action")
    def test_create_and_delete_report_saved_view_events(self, report_user_action) -> None:
        Dashboard.objects.create(team=self.team, name="First dashboard", created_by=self.user)
        Dashboard.objects.create(team=self.team, name="Second dashboard", created_by=self.user)
        response = self.client.post(self.base_url, self._payload(), format="json")

        assert response.status_code == status.HTTP_201_CREATED, response.json()
        saved_view = response.json()
        create_event = report_user_action.call_args
        assert create_event.args[:3] == (
            self.user,
            "dashboard saved view created",
            {
                "saved_view_id": saved_view["id"],
                "scope": "private",
                "has_search_filter": False,
                "has_folder_filter": False,
                "has_tag_filter": True,
                "tag_count": 1,
                "has_creator_filter": False,
                "is_pinned": False,
                "is_shared": True,
                "active_filter_count": 2,
                "saved_views_created_by_user_count": 1,
                "dashboards_created_by_user_count": 2,
            },
        )
        assert create_event.kwargs["team"] == self.team
        assert create_event.kwargs["request"] is not None

        response = self.client.delete(f"{self.base_url}{saved_view['id']}/")

        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert [call.args[1] for call in report_user_action.call_args_list] == [
            "dashboard saved view created",
            "dashboard saved view deleted",
        ]
        assert not DashboardSavedView.all_teams.filter(pk=saved_view["id"]).exists()

    @patch("products.dashboards.backend.api.dashboard_saved_view.report_user_action")
    def test_update_reports_filter_shape(self, report_user_action) -> None:
        response = self.client.post(self.base_url, self._payload(), format="json")
        assert response.status_code == status.HTTP_201_CREATED, response.json()

        response = self.client.patch(
            f"{self.base_url}{response.json()['id']}/",
            {"filters": {"search": "dashboard", "pinned": True}},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK, response.json()
        update_event = report_user_action.call_args
        assert update_event.args[:3] == (
            self.user,
            "dashboard saved view updated",
            {
                "saved_view_id": response.json()["id"],
                "scope": "private",
                "changed_fields": ["filters"],
                "has_search_filter": True,
                "has_folder_filter": False,
                "has_tag_filter": False,
                "tag_count": 0,
                "has_creator_filter": False,
                "is_pinned": True,
                "is_shared": False,
                "active_filter_count": 2,
            },
        )
