from datetime import timedelta

from posthog.test.base import APIBaseTest

from django.conf import settings
from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models.oauth import OAuthAccessToken, OAuthApplication
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.organization_domain import OrganizationDomain
from posthog.models.organization_ip_restrictions import OrganizationIPRestrictions
from posthog.models.team import Team

from products.access_control.backend.models.access_control import AccessControl

HEATMAPS_FEATURE = [{"key": AvailableFeature.TOOLBAR_HEATMAPS, "name": AvailableFeature.TOOLBAR_HEATMAPS}]


class TestToolbarEntitlementsRoute(APIBaseTest):
    def setUp(self):
        super().setUp()

        self.other_organization = Organization.objects.create(name="Current organization")
        self.other_team = Team.objects.create(organization=self.other_organization, name="Current project")
        OrganizationMembership.objects.create(organization=self.other_organization, user=self.user)
        self.user.current_organization = self.other_organization
        self.user.current_team = self.other_team
        self.user.save(update_fields=["current_organization", "current_team"])

        self.toolbar_app = OAuthApplication.objects.create(
            name=settings.TOOLBAR_OAUTH_APPLICATION_NAME,
            client_type=OAuthApplication.CLIENT_PUBLIC,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://example.com/callback",
            algorithm="RS256",
            organization=self.organization,
            user=self.user,
        )

    def _url(self) -> str:
        return f"/api/projects/{self.team.id}/toolbar/entitlements/"

    def _toolbar_token(self, scoped_team: Team) -> str:
        token = OAuthAccessToken.objects.create(
            user=self.user,
            application=self.toolbar_app,
            token=f"pha_toolbar_entitlements_{scoped_team.id}",
            expires=timezone.now() + timedelta(hours=1),
            scope=" ".join(settings.TOOLBAR_OAUTH_SCOPES),
            scoped_teams=[scoped_team.id],
        )
        return token.token

    @parameterized.expand(
        [
            ("url_organization_entitled", HEATMAPS_FEATURE, [], True),
            ("current_organization_entitled", [], HEATMAPS_FEATURE, False),
        ]
    )
    def test_entitlements_follow_the_organization_of_the_url_team(
        self, _name, url_organization_features, current_organization_features, expected
    ):
        self.organization.available_product_features = url_organization_features
        self.organization.save()
        self.other_organization.available_product_features = current_organization_features
        self.other_organization.save()
        self.client.logout()

        with self.is_cloud(True):
            response = self.client.get(self._url(), HTTP_AUTHORIZATION=f"Bearer {self._toolbar_token(self.team)}")

        assert response.status_code == status.HTTP_200_OK, response.content
        assert response.json() == {"entitlements": {AvailableFeature.TOOLBAR_HEATMAPS: expected}}

    def test_denied_without_toolbar_access_to_the_url_team(self):
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save()
        AccessControl.objects.create(
            team=self.team,
            resource="toolbar",
            resource_id=None,
            access_level="none",
            organization_member=self.organization_membership,
        )

        response = self.client.get(self._url())

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.content

    def test_token_scoped_to_another_team_is_rejected(self):
        self.client.logout()

        response = self.client.get(self._url(), HTTP_AUTHORIZATION=f"Bearer {self._toolbar_token(self.other_team)}")

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.content

    @parameterized.expand([("ip_allowlist", "ip_not_allowed"), ("verified_domains", "verified_domain_required")])
    def test_rejected_when_the_url_teams_organization_restricts_access(self, restriction, expected_code):
        if restriction == "ip_allowlist":
            with self.captureOnCommitCallbacks(execute=True):
                OrganizationIPRestrictions.objects.create(
                    organization=self.organization, ip_restrictions=["203.0.113.0/24"]
                )
        else:
            self.organization.enforce_verified_domains = True
            self.organization.save()
            OrganizationDomain.objects.create(
                domain="hogflix.com", organization=self.organization, verified_at=timezone.now()
            )

        response = self.client.get(self._url(), REMOTE_ADDR="198.51.100.7")

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.content
        assert response.json()["code"] == expected_code
