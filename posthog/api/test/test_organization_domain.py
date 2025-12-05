import datetime
from zoneinfo import ZoneInfo

from freezegun import freeze_time
from posthog.test.base import APIBaseTest, BaseTest
from unittest.mock import ANY, patch

from django.utils import timezone

import dns.rrset
import dns.resolver
from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models import Organization, OrganizationDomain, OrganizationMembership, Team


class FakeAnswer:
    def __init__(self, answer):
        self.answer = answer


class FakeDNSResponse:
    def __init__(self, answer):
        self.response = FakeAnswer(answer)


class TestOrganizationDomains(BaseTest):
    def test_continuous_verification_task(self):
        """
        Tests the task that re-verifies domains to ensure ownership is maintained.
        """
        pass


class TestOrganizationDomainsAPI(APIBaseTest):
    domain: OrganizationDomain = None  # type: ignore
    another_domain: OrganizationDomain = None  # type: ignore
    another_org: Organization = None  # type: ignore

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.domain = OrganizationDomain.objects.create(organization=cls.organization, domain="myposthog.com")

        cls.another_org = Organization.objects.create(name="Another Org")
        Team.objects.create(organization=cls.another_org)
        cls.another_domain = OrganizationDomain.objects.create(organization=cls.another_org, domain="org.posthog.net")

    # List & retrieve domains

    def test_can_list_and_retrieve_domains(self):
        response = self.client.get("/api/organizations/@current/domains")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        self.assertEqual(response_data["count"], 1)
        item = response_data["results"][0]

        self.assertEqual(item["domain"], "myposthog.com")
        self.assertEqual(item["verified_at"], None)
        self.assertEqual(item["is_verified"], False)
        self.assertEqual(item["jit_provisioning_enabled"], False)
        self.assertEqual(item["sso_enforcement"], "")
        self.assertRegex(item["verification_challenge"], r"[0-9A-Za-z_-]{32}")

        retrieve_response = self.client.get(f"/api/organizations/{self.organization.id}/domains/{self.domain.id}")
        self.assertEqual(retrieve_response.status_code, status.HTTP_200_OK)
        self.assertEqual(retrieve_response.json(), response_data["results"][0])

    def test_cannot_list_or_retrieve_domains_for_other_org(self):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        response = self.client.get(f"/api/organizations/@current/domains/{self.another_domain.id}")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.json(), self.not_found_response())

        response = self.client.get(f"/api/organizations/{self.another_org.id}/domains/{self.another_domain.id}")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.json(), self.permission_denied_response())

    # Create domains

    @patch("posthoganalytics.capture")
    def test_create_domain(self, mock_capture):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization.available_product_features = [
            {"key": "automatic_provisioning", "name": "automatic_provisioning"}
        ]
        self.organization.save()
        self.organization_membership.save()

        with self.is_cloud(True):
            response = self.client.post(
                "/api/organizations/@current/domains/",
                {
                    "domain": "the.posthog.com",
                    "verified_at": "2022-01-01T14:25:25.000Z",  # ignore me
                    "verification_challenge": "123",  # ignore me
                    "jit_provisioning_enabled": True,  # ignore me
                    "sso_enforcement": "saml",  # ignore me
                    "scim_enabled": True,  # ignore me
                },
            )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        response_data = response.json()
        self.assertEqual(response_data["domain"], "the.posthog.com")
        self.assertEqual(response_data["verified_at"], None)
        self.assertEqual(response_data["jit_provisioning_enabled"], False)
        self.assertEqual(response_data["scim_enabled"], False)
        self.assertRegex(response_data["verification_challenge"], r"[0-9A-Za-z_-]{32}")

        instance = OrganizationDomain.objects.get(id=response_data["id"])
        self.assertEqual(instance.domain, "the.posthog.com")
        self.assertEqual(instance.verified_at, None)
        self.assertEqual(instance.last_verification_retry, None)
        self.assertEqual(instance.sso_enforcement, "")
        self.assertEqual(instance.scim_enabled, False)

        # Verify the domain creation capture event was called
        mock_capture.assert_any_call(
            event="organization domain created",
            distinct_id=self.user.distinct_id,
            properties={
                "domain": "the.posthog.com",
                "jit_provisioning_enabled": False,
                "sso_enforcement": None,
            },
            groups={"instance": ANY, "organization": str(self.organization.id)},
        )

    def test_cant_create_domain_without_feature(self):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        with self.is_cloud(True):
            response = self.client.post(
                "/api/organizations/@current/domains/",
                {
                    "domain": "the.posthog.com",
                    "verified_at": "2022-01-01T14:25:25.000Z",  # ignore me
                    "verification_challenge": "123",  # ignore me
                    "jit_provisioning_enabled": True,  # ignore me
                    "sso_enforcement": "saml",  # ignore me
                },
            )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_cannot_create_duplicate_domain(self):
        OrganizationDomain.objects.create(domain="i-registered-first.com", organization=self.another_org)
        count = OrganizationDomain.objects.count()
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        response = self.client.post("/api/organizations/@current/domains/", {"domain": "i-registered-first.com"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            {
                "type": "validation_error",
                "code": "unique",
                "detail": "domain with this domain already exists.",
                "attr": "domain",
            },
        )

        self.assertEqual(OrganizationDomain.objects.count(), count)

    def test_cannot_create_invalid_domain(self):
        count = OrganizationDomain.objects.count()
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        invalid_domains = [
            "test@posthog.com",
            "🦔🦔🦔.com",
            "one.two.c",
            "--alpha.com",
            "javascript: alert(1)",
        ]

        for _domain in invalid_domains:
            response = self.client.post("/api/organizations/@current/domains/", {"domain": _domain})
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertEqual(
                response.json(),
                {
                    "type": "validation_error",
                    "code": "invalid_input",
                    "detail": "Please enter a valid domain or subdomain name.",
                    "attr": "domain",
                },
            )

        self.assertEqual(OrganizationDomain.objects.count(), count)

    @patch("posthog.models.organization_domain.dns.resolver.resolve")
    def test_can_request_verification_for_unverified_domains(self, mock_dns_query):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        mock_dns_query.return_value = FakeDNSResponse(
            [
                dns.rrset.from_text(
                    "_posthog-challenge.myposthog.com.",
                    3600,
                    "IN",
                    "TXT",
                    self.domain.verification_challenge,
                )
            ]
        )

        with freeze_time("2021-08-08T20:20:08Z"):
            response = self.client.post(f"/api/organizations/@current/domains/{self.domain.id}/verify")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        self.domain.refresh_from_db()
        self.assertEqual(response_data["domain"], "myposthog.com")
        self.assertEqual(
            response_data["verified_at"],
            self.domain.verified_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
        self.assertEqual(response_data["is_verified"], True)

        self.assertEqual(
            self.domain.verified_at,
            datetime.datetime(2021, 8, 8, 20, 20, 8, tzinfo=ZoneInfo("UTC")),
        )
        self.assertEqual(self.domain.is_verified, True)

    @patch("posthog.models.organization_domain.dns.resolver.resolve")
    def test_domain_is_not_verified_with_missing_challenge(self, mock_dns_query):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        mock_dns_query.side_effect = dns.resolver.NoAnswer()

        with freeze_time("2021-10-10T10:10:10Z"):
            with self.is_cloud(True):
                response = self.client.post(f"/api/organizations/@current/domains/{self.domain.id}/verify")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        self.domain.refresh_from_db()
        self.assertEqual(response_data["domain"], "myposthog.com")
        self.assertEqual(response_data["verified_at"], None)
        self.assertEqual(self.domain.verified_at, None)
        self.assertEqual(
            self.domain.last_verification_retry,
            datetime.datetime(2021, 10, 10, 10, 10, 10, tzinfo=ZoneInfo("UTC")),
        )

    @patch("posthog.models.organization_domain.dns.resolver.resolve")
    def test_domain_is_not_verified_with_missing_domain(self, mock_dns_query):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        mock_dns_query.side_effect = dns.resolver.NXDOMAIN()

        with freeze_time("2021-10-10T10:10:10Z"):
            with self.is_cloud(True):
                response = self.client.post(f"/api/organizations/@current/domains/{self.domain.id}/verify")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        self.domain.refresh_from_db()
        self.assertEqual(response_data["domain"], "myposthog.com")
        self.assertEqual(response_data["verified_at"], None)
        self.assertEqual(self.domain.verified_at, None)
        self.assertEqual(
            self.domain.last_verification_retry,
            datetime.datetime(2021, 10, 10, 10, 10, 10, tzinfo=ZoneInfo("UTC")),
        )

    @patch("posthog.models.organization_domain.dns.resolver.resolve")
    def test_domain_is_not_verified_with_incorrect_challenge(self, mock_dns_query):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        mock_dns_query.return_value = FakeDNSResponse(
            [
                dns.rrset.from_text(
                    "_posthog-challenge.myposthog.com.",
                    3600,
                    "IN",
                    "TXT",
                    "incorrect_challenge",
                )
            ]
        )

        with freeze_time("2021-10-10T10:10:10Z"):
            with self.is_cloud(True):
                response = self.client.post(f"/api/organizations/@current/domains/{self.domain.id}/verify")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        self.domain.refresh_from_db()
        self.assertEqual(response_data["domain"], "myposthog.com")
        self.assertEqual(response_data["verified_at"], None)
        self.assertEqual(self.domain.verified_at, None)
        self.assertEqual(
            self.domain.last_verification_retry,
            datetime.datetime(2021, 10, 10, 10, 10, 10, tzinfo=ZoneInfo("UTC")),
        )

    def test_cannot_request_verification_for_verified_domains(self):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        self.domain.verified_at = timezone.now()
        self.domain.save()

        response = self.client.post(f"/api/organizations/@current/domains/{self.domain.id}/verify")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            {
                "type": "validation_error",
                "code": "already_verified",
                "detail": "This domain has already been verified.",
                "attr": None,
            },
        )

    def test_only_admin_can_create_verified_domains(self):
        count = OrganizationDomain.objects.count()
        response = self.client.post("/api/organizations/@current/domains/", {"domain": "evil.posthog.com"})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            response.json(),
            self.permission_denied_response("Your organization access level is insufficient."),
        )

        self.assertEqual(OrganizationDomain.objects.count(), count)

    def test_only_admin_can_request_verification(self):
        response = self.client.post(f"/api/organizations/@current/domains/{self.domain.id}/verify")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            response.json(),
            self.permission_denied_response("Your organization access level is insufficient."),
        )

        self.domain.refresh_from_db()
        self.assertEqual(self.domain.verified_at, None)

    # Update domains

    def test_can_update_jit_provisioning_and_sso_enforcement(self):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization.available_product_features = [
            {"key": "automatic_provisioning", "name": "automatic_provisioning"}
        ]
        self.organization_membership.save()
        self.organization.save()
        self.domain.verified_at = timezone.now()
        self.domain.save()

        response = self.client.patch(
            f"/api/organizations/@current/domains/{self.domain.id}/",
            {"sso_enforcement": "google-oauth2", "jit_provisioning_enabled": True},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["sso_enforcement"], "google-oauth2")
        self.assertEqual(response.json()["jit_provisioning_enabled"], True)

        self.domain.refresh_from_db()
        self.assertEqual(self.domain.sso_enforcement, "google-oauth2")
        self.assertEqual(self.domain.jit_provisioning_enabled, True)

    def test_cannot_enforce_sso_or_enable_jit_provisioning_on_unverified_domain(self):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        # SSO Enforcement
        response = self.client.patch(
            f"/api/organizations/@current/domains/{self.domain.id}/",
            {"sso_enforcement": "google-oauth2"},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            {
                "type": "validation_error",
                "code": "verification_required",
                "detail": "This attribute cannot be updated until the domain is verified.",
                "attr": "sso_enforcement",
            },
        )
        self.domain.refresh_from_db()
        self.assertEqual(self.domain.sso_enforcement, "")

        # JIT Provisioning
        response = self.client.patch(
            f"/api/organizations/@current/domains/{self.domain.id}/",
            {"jit_provisioning_enabled": True},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            {
                "type": "validation_error",
                "code": "verification_required",
                "detail": "This attribute cannot be updated until the domain is verified.",
                "attr": "jit_provisioning_enabled",
            },
        )
        self.domain.refresh_from_db()
        self.assertEqual(self.domain.jit_provisioning_enabled, False)

    def test_only_allowed_parameters_can_be_updated(self):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        response = self.client.patch(
            f"/api/organizations/@current/domains/{self.domain.id}/",
            {"verified_at": "2020-01-01T12:12:12Z", "verification_challenge": "123"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["verified_at"], None)
        self.assertRegex(response.json()["verification_challenge"], r"[0-9A-Za-z_-]{32}")

    def test_only_admin_can_update_domain(self):
        self.domain.verified_at = timezone.now()
        self.domain.save()

        response = self.client.patch(
            f"/api/organizations/{self.organization.id}/domains/{self.domain.id}/",
            {"sso_enforcement": "google-oauth2", "jit_provisioning_enabled": True},
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            response.json(),
            self.permission_denied_response("Your organization access level is insufficient."),
        )
        self.domain.refresh_from_db()
        self.assertEqual(self.domain.jit_provisioning_enabled, False)
        self.assertEqual(self.domain.sso_enforcement, "")

    def test_cannot_update_domain_for_another_org(self):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        self.another_domain.verified_at = timezone.now()
        self.another_domain.save()

        response = self.client.patch(
            f"/api/organizations/{self.another_org.id}/domains/{self.another_domain.id}/",
            {"sso_enforcement": "google-oauth2", "jit_provisioning_enabled": True},
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.json(), self.permission_denied_response())
        self.another_domain.refresh_from_db()
        self.assertEqual(self.another_domain.jit_provisioning_enabled, False)
        self.assertEqual(self.another_domain.sso_enforcement, "")

    # Delete domains

    @patch("posthoganalytics.capture")
    def test_admin_can_delete_domain(self, mock_capture):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        response = self.client.delete(f"/api/organizations/@current/domains/{self.domain.id}")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(response.content, b"")

        self.assertFalse(OrganizationDomain.objects.filter(id=self.domain.id).exists())

        # Verify the domain deletion capture event was called
        mock_capture.assert_any_call(
            event="organization domain deleted",
            distinct_id=self.user.distinct_id,
            properties={
                "domain": "myposthog.com",
                "is_verified": False,
                "had_saml": False,
                "had_jit_provisioning": False,
                "had_sso_enforcement": False,
                "had_scim": False,
            },
            groups={"instance": ANY, "organization": str(self.organization.id)},
        )

    def test_only_admin_can_delete_domain(self):
        response = self.client.delete(f"/api/organizations/@current/domains/{self.domain.id}")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            response.json(),
            self.permission_denied_response("Your organization access level is insufficient."),
        )
        self.domain.refresh_from_db()

    def test_cannot_delete_domain_for_another_org(self):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        response = self.client.delete(f"/api/organizations/{self.another_org.id}/domains/{self.another_domain.id}")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.json(), self.permission_denied_response())
        self.another_domain.refresh_from_db()

    # SCIM configuration

    def test_can_enable_scim(self):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization.available_product_features = [{"key": AvailableFeature.SCIM, "name": "SCIM"}]
        self.organization_membership.save()
        self.organization.save()
        self.domain.verified_at = timezone.now()
        self.domain.save()

        response = self.client.patch(
            f"/api/organizations/@current/domains/{self.domain.id}/",
            {"scim_enabled": True},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["scim_enabled"], True)
        self.assertIsNotNone(response.json()["scim_bearer_token"])
        self.assertIn("scim_base_url", response.json())

        self.domain.refresh_from_db()
        self.assertEqual(self.domain.scim_enabled, True)
        self.assertIsNotNone(self.domain.scim_bearer_token)

    def test_cannot_enable_scim_without_available_feature(self):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        self.domain.verified_at = timezone.now()
        self.domain.save()

        response = self.client.patch(
            f"/api/organizations/@current/domains/{self.domain.id}/",
            {"scim_enabled": True},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("not available", response.json()["detail"].lower())

    def test_cannot_enable_scim_on_unverified_domain(self):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization.available_product_features = [{"key": AvailableFeature.SCIM, "name": "SCIM"}]
        self.organization_membership.save()
        self.organization.save()

        response = self.client.patch(
            f"/api/organizations/@current/domains/{self.domain.id}/",
            {"scim_enabled": True},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            {
                "type": "validation_error",
                "code": "verification_required",
                "detail": "This attribute cannot be updated until the domain is verified.",
                "attr": "scim_enabled",
            },
        )

    def test_can_disable_scim(self):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization.available_product_features = [{"key": AvailableFeature.SCIM, "name": "SCIM"}]
        self.organization_membership.save()
        self.organization.save()
        self.domain.verified_at = timezone.now()
        self.domain.save()

        # First enable SCIM
        enable_response = self.client.patch(
            f"/api/organizations/@current/domains/{self.domain.id}/",
            {"scim_enabled": True},
        )
        self.assertEqual(enable_response.status_code, status.HTTP_200_OK)

        # Then disable it
        response = self.client.patch(
            f"/api/organizations/@current/domains/{self.domain.id}/",
            {"scim_enabled": False},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["scim_enabled"], False)
        self.assertIsNone(response.json()["scim_bearer_token"])

        self.domain.refresh_from_db()
        self.assertEqual(self.domain.scim_enabled, False)
        self.assertIsNone(self.domain.scim_bearer_token)

    def test_can_regenerate_scim_token(self):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization.available_product_features = [{"key": AvailableFeature.SCIM, "name": "SCIM"}]
        self.organization_membership.save()
        self.organization.save()
        self.domain.verified_at = timezone.now()
        self.domain.save()

        # First enable SCIM
        enable_response = self.client.patch(
            f"/api/organizations/@current/domains/{self.domain.id}/",
            {"scim_enabled": True},
        )
        self.assertEqual(enable_response.status_code, status.HTTP_200_OK)
        original_token = enable_response.json()["scim_bearer_token"]

        # Regenerate token
        response = self.client.post(f"/api/organizations/@current/domains/{self.domain.id}/scim/token")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["scim_enabled"], True)
        new_token = response.json()["scim_bearer_token"]
        self.assertIsNotNone(new_token)
        self.assertNotEqual(original_token, new_token)

    def test_cannot_regenerate_scim_token_without_available_feature(self):
        from ee.api.scim.auth import generate_scim_token

        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        self.domain.verified_at = timezone.now()
        self.domain.save()

        # Manually enable SCIM (bypassing validation)
        plain_token, hashed_token = generate_scim_token()
        self.domain.scim_enabled = True
        self.domain.scim_bearer_token = hashed_token
        self.domain.save()

        # Remove feature
        self.organization.available_product_features = []
        self.organization.save()

        response = self.client.post(f"/api/organizations/@current/domains/{self.domain.id}/scim/token")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
