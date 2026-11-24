from posthog.test.base import APIBaseTest

from parameterized import parameterized
from rest_framework import status
from rest_framework.test import APIClient

from posthog.models.oauth import OAuthApplication
from posthog.models.oauth_provisioning import ProvisioningConfig
from posthog.models.oauth_provisioning_review import CIMDProvisioningReview, ProvisioningReviewStatus
from posthog.models.organization import Organization, OrganizationMembership


class TestOrganizationOAuthApplicationViewSet(APIBaseTest):
    expected_fields = {
        "id",
        "name",
        "client_id",
        "redirect_uris_list",
        "is_verified",
        "is_cimd_client",
        "provisioning_status",
        "provisioning_review",
        "created",
        "updated",
    }

    def setUp(self):
        super().setUp()
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

    def _create_app(self, organization, name="Test App", redirect_uris="https://example.com/callback", **kwargs):
        return OAuthApplication.objects.create(
            name=name,
            redirect_uris=redirect_uris,
            organization=organization,
            user=self.user,
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            algorithm="RS256",
            **kwargs,
        )

    def test_list_returns_apps_for_current_org(self):
        app = self._create_app(self.organization, name="My App")
        response = self.client.get("/api/organizations/@current/oauth_applications/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["id"], str(app.id))
        self.assertEqual(response.data["results"][0]["name"], "My App")

    def test_list_does_not_return_apps_from_other_org(self):
        other_org = Organization.objects.create(name="Other Org")
        self._create_app(self.organization, name="My App")
        self._create_app(other_org, name="Other App")

        response = self.client.get("/api/organizations/@current/oauth_applications/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["name"], "My App")

    def test_list_returns_empty_when_no_apps(self):
        response = self.client.get("/api/organizations/@current/oauth_applications/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 0)
        self.assertEqual(response.data["results"], [])

    def test_response_contains_only_expected_fields(self):
        self._create_app(self.organization)
        response = self.client.get("/api/organizations/@current/oauth_applications/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(set(response.data["results"][0].keys()), self.expected_fields)

    @parameterized.expand(["client_secret", "redirect_uris", "skip_authorization", "algorithm", "user"])
    def test_sensitive_field_not_exposed(self, field_name):
        self._create_app(self.organization)
        response = self.client.get("/api/organizations/@current/oauth_applications/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertNotIn(field_name, response.data["results"][0])

    def test_redirect_uris_list_splits_space_separated_uris(self):
        self._create_app(self.organization, redirect_uris="https://a.com/cb https://b.com/cb")
        response = self.client.get("/api/organizations/@current/oauth_applications/")

        self.assertEqual(response.data["results"][0]["redirect_uris_list"], ["https://a.com/cb", "https://b.com/cb"])

    def test_list_ordered_by_most_recent_first(self):
        app1 = self._create_app(self.organization, name="First")
        app2 = self._create_app(self.organization, name="Second")
        response = self.client.get("/api/organizations/@current/oauth_applications/")

        self.assertEqual(response.data["results"][0]["id"], str(app2.id))
        self.assertEqual(response.data["results"][1]["id"], str(app1.id))

    def test_unauthenticated_request_is_rejected(self):
        unauthenticated_client = APIClient()
        response = unauthenticated_client.get("/api/organizations/@current/oauth_applications/")

        self.assertIn(response.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])

    def test_read_only_no_create(self):
        response = self.client.post(
            "/api/organizations/@current/oauth_applications/",
            {"name": "New App"},
        )
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_detail_returns_an_app_of_the_current_org_only(self):
        app = self._create_app(self.organization)
        other = self._create_app(Organization.objects.create(name="Other Org"))

        own = self.client.get(f"/api/organizations/@current/oauth_applications/{app.id}/")
        foreign = self.client.get(f"/api/organizations/@current/oauth_applications/{other.id}/")

        self.assertEqual(own.status_code, status.HTTP_200_OK)
        self.assertEqual(foreign.status_code, status.HTTP_404_NOT_FOUND)

    def test_members_who_are_not_admins_are_refused(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        self._create_app(self.organization)

        response = self.client.get("/api/organizations/@current/oauth_applications/")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    @parameterized.expand(
        [
            ("not_a_partner", False, ProvisioningConfig(), None, "not_a_partner"),
            ("in_review", True, ProvisioningConfig(), ProvisioningReviewStatus.PENDING, "in_review"),
            (
                "waiting_for_staff",
                True,
                ProvisioningConfig(),
                ProvisioningReviewStatus.NEEDS_HUMAN,
                "waiting_for_staff",
            ),
            ("on", True, ProvisioningConfig(active=True), ProvisioningReviewStatus.ACCEPTED, "on"),
            ("blocked", True, ProvisioningConfig(disabled=True), ProvisioningReviewStatus.REJECTED, "blocked"),
            # Every partner gate reads `active` alone, so this partner still provisions.
            ("active_and_disabled", True, ProvisioningConfig(active=True, disabled=True), None, "on"),
        ]
    )
    def test_provisioning_status_and_review(self, _name, is_partner, config, review_status, expected_status):
        app = self._create_app(
            self.organization,
            is_provisioning_partner=is_partner,
            _provisioning_config=config.model_dump(mode="json"),
        )
        if review_status is not None:
            CIMDProvisioningReview.objects.create(
                application=app,
                domain="example.com",
                status=review_status,
                reason="Research: legitimate 0.12, malicious 0.81",
                partner_message="Host the document on your product's domain, then register again.",
            )

        result = self.client.get("/api/organizations/@current/oauth_applications/").json()["results"][0]

        self.assertEqual(result["provisioning_status"], expected_status)
        if review_status is None:
            self.assertIsNone(result["provisioning_review"])
        else:
            self.assertEqual(
                set(result["provisioning_review"]), {"status", "opened_at", "decided_at", "partner_message"}
            )
            self.assertEqual(result["provisioning_review"]["status"], review_status)
            self.assertNotIn("legitimate", str(result))
