from posthog.test.base import APIBaseTest
from unittest.mock import patch

from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models import Organization, OrganizationMembership, Team

from products.access_control.backend.models.access_control import AccessControl


@patch("posthog.guest_access.api.guest_mode_active", return_value=True)
class TestGuestPermission(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization.available_product_features = [
            {"key": AvailableFeature.ADVANCED_PERMISSIONS, "name": "Advanced permissions"}
        ]
        self.organization.save()
        self.organization_membership.level = OrganizationMembership.Level.GUEST
        self.organization_membership.save()
        # A guest invite always creates this project rule, which admits the guest to the project.
        AccessControl.objects.create(
            team=self.team,
            resource="project",
            resource_id=str(self.team.id),
            organization_member=self.organization_membership,
            access_level="member",
        )

    def test_guest_is_denied_endpoints_outside_the_allowlist(self, _active) -> None:
        response = self.client.get(f"/api/projects/{self.team.id}/feature_flags/")
        assert response.status_code == status.HTTP_403_FORBIDDEN, response.json()

    def test_guest_can_read_their_own_user(self, _active) -> None:
        response = self.client.get("/api/users/@me/")
        assert response.status_code == status.HTTP_200_OK, response.json()

    def test_guest_cannot_create_personal_api_keys(self, _active) -> None:
        response = self.client.post("/api/personal_api_keys/", {"label": "key", "scopes": ["*"]})
        assert response.status_code == status.HTTP_403_FORBIDDEN, response.json()

    def test_guest_is_rejected_everywhere_without_the_entitlement(self, _active) -> None:
        self.organization.available_product_features = []
        self.organization.save()
        response = self.client.get("/api/users/@me/")
        assert response.status_code == status.HTTP_403_FORBIDDEN, response.json()

    def test_guest_rules_pass_through_when_the_org_is_not_on_v2(self, active) -> None:
        active.return_value = False
        response = self.client.get(f"/api/projects/{self.team.id}/feature_flags/")
        assert response.status_code == status.HTTP_200_OK, response.json()

    def test_guest_rules_follow_the_requested_organization(self, _active) -> None:
        other = Organization.objects.create(name="Own org")
        OrganizationMembership.objects.create(
            organization=other, user=self.user, level=OrganizationMembership.Level.MEMBER
        )
        other_team = Team.objects.create(organization=other, name="Own project")
        response = self.client.get(f"/api/projects/{other_team.id}/feature_flags/")
        assert response.status_code == status.HTTP_200_OK, response.json()
