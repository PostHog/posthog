from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.guest_access import guest_effective_resource_access
from posthog.models import OrganizationMembership, Team, User

from products.access_control.backend.models.access_control import AccessControl
from products.authz.backend.facade.contracts import Resource, ResourceIds
from products.authz.backend.facade.enums import ResourceType


class TestGuestSerializers(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization.available_product_features = [
            {"key": AvailableFeature.ADVANCED_PERMISSIONS, "name": "Advanced permissions"}
        ]
        self.organization.save()
        self.organization_membership.level = OrganizationMembership.Level.GUEST
        self.organization_membership.save()
        AccessControl.objects.create(
            team=self.team,
            resource="project",
            resource_id=str(self.team.id),
            organization_member=self.organization_membership,
            access_level="member",
        )
        self.other_team = Team.objects.create(organization=self.organization, name="Other project")
        flag = patch("products.authz.backend.logic.rollout.get_feature_flag_or_none", return_value="v2")
        flag.start()
        self.addCleanup(flag.stop)

    def test_guest_sees_only_their_project_and_no_member_count(self) -> None:
        response = self.client.get("/api/organizations/@current/")
        assert response.status_code == status.HTTP_200_OK, response.json()
        data = response.json()
        assert [team["id"] for team in data["teams"]] == [self.team.id]
        assert [project["id"] for project in data["projects"]] == [self.team.project_id]
        assert data["member_count"] is None

    def test_guest_reads_their_project_without_its_secrets(self) -> None:
        response = self.client.get(f"/api/projects/{self.team.id}/")
        assert response.status_code == status.HTTP_200_OK, response.json()
        data = response.json()
        assert data["secret_api_token"] is None
        assert data["live_events_token"] is None

    @parameterized.expand([("access control on", True), ("access control off", False)])
    def test_guest_cannot_open_a_project_without_a_rule(self, _name: str, access_control: bool) -> None:
        if access_control:
            self.organization.available_product_features = [
                {"key": AvailableFeature.ADVANCED_PERMISSIONS, "name": "Advanced permissions"},
                {"key": AvailableFeature.ACCESS_CONTROL, "name": "Access control"},
            ]
            self.organization.save()
        response = self.client.get(f"/api/projects/{self.other_team.id}/")
        assert response.status_code in (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND), response.json()

    def test_guest_cannot_switch_to_a_project_without_a_rule(self) -> None:
        response = self.client.patch("/api/users/@me/", {"set_current_team": self.other_team.id})
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        self.user.refresh_from_db()
        assert self.user.current_team_id == self.team.id

    def test_guest_org_switch_lands_on_their_project(self) -> None:
        AccessControl.objects.filter(organization_member=self.organization_membership).update(
            team=self.other_team, resource_id=str(self.other_team.id)
        )
        response = self.client.patch("/api/users/@me/", {"set_current_organization": str(self.organization.id)})
        assert response.status_code == status.HTTP_200_OK, response.json()
        self.user.refresh_from_db()
        assert self.user.current_team_id == self.other_team.id

    def test_guest_page_moves_them_off_a_project_without_a_rule(self) -> None:
        User.objects.filter(pk=self.user.pk).update(current_team=self.other_team)
        response = self.client.get("/")
        assert response.status_code == status.HTTP_200_OK
        assert b"Other project" not in response.content
        self.user.refresh_from_db()
        assert self.user.current_team_id == self.team.id

    def test_guest_without_a_current_project_lands_on_their_project(self) -> None:
        AccessControl.objects.filter(organization_member=self.organization_membership).update(
            team=self.other_team, resource_id=str(self.other_team.id)
        )
        User.objects.filter(pk=self.user.pk).update(current_team=None)
        response = self.client.get("/api/users/@me/")
        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json()["team"]["id"] == self.other_team.id

    def test_guest_app_access_shows_only_granted_types(self) -> None:
        def openfga_list(resource: Resource, *_args: object) -> ResourceIds:
            granted = {ResourceType.DASHBOARD: frozenset({"1"})}
            return ResourceIds(ids=granted.get(resource.type, frozenset()), complete=True)

        with patch("products.authz.backend.logic.authorization.list_resources", side_effect=openfga_list):
            access = guest_effective_resource_access(self.user, self.team)
        assert access["dashboard"] == "viewer"
        assert {access["insight"], access["notebook"], access["feature_flag"], access["session_recording"]} == {"none"}
