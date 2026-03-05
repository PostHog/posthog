from freezegun import freeze_time
from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.utils import timezone

import dns.rrset
import dns.resolver
from parameterized import parameterized

from posthog.constants import AvailableFeature
from posthog.models import OrganizationDomain, OrganizationMembership
from posthog.models.activity_logging.activity_log import ActivityLog


class FakeAnswer:
    def __init__(self, answer):
        self.answer = answer


class FakeDNSResponse:
    def __init__(self, answer):
        self.response = FakeAnswer(answer)


class TestOrganizationDomainActivityLogging(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

    def _create_verified_domain(self, domain="test.example.com"):
        response = self.client.post(
            "/api/organizations/@current/domains/",
            {"domain": domain},
        )
        self.assertEqual(response.status_code, 201)
        domain_obj = OrganizationDomain.objects.get(id=response.json()["id"])
        domain_obj.verified_at = timezone.now()
        domain_obj.save()
        ActivityLog.objects.filter(
            organization_id=self.organization.id,
            scope="OrganizationDomain",
        ).delete()
        return domain_obj

    def test_domain_creation_activity_logging(self):
        response = self.client.post(
            "/api/organizations/@current/domains/",
            {"domain": "new.example.com"},
        )
        self.assertEqual(response.status_code, 201)

        log = ActivityLog.objects.filter(
            organization_id=self.organization.id,
            scope="OrganizationDomain",
            activity="created",
        ).first()

        assert log is not None
        assert log.detail is not None
        self.assertEqual(log.user, self.user)
        self.assertIn("new.example.com", log.detail["name"])
        self.assertIn(self.organization.name, log.detail["name"])

        context = log.detail.get("context", {})
        self.assertEqual(context["organization_id"], str(self.organization.id))
        self.assertEqual(context["domain"], "new.example.com")

    def test_domain_deletion_activity_logging(self):
        domain = self._create_verified_domain("delete-me.example.com")
        domain_id = str(domain.id)

        response = self.client.delete(f"/api/organizations/@current/domains/{domain.id}")
        self.assertEqual(response.status_code, 204)

        log = ActivityLog.objects.filter(
            organization_id=self.organization.id,
            scope="OrganizationDomain",
            activity="deleted",
        ).first()

        assert log is not None
        assert log.detail is not None
        self.assertEqual(log.item_id, domain_id)
        self.assertIn("delete-me.example.com", log.detail["name"])
        self.assertIn("removed", log.detail["name"])

    @parameterized.expand(
        [
            ("sso-enforcement", "sso_enforcement", "google-oauth2", "SSO enforcement", None, "google-oauth2"),
            (
                "saml-entity-id",
                "saml_entity_id",
                "https://idp.example.com",
                "SAML entity ID",
                None,
                "https://idp.example.com",
            ),
            (
                "saml-acs-url",
                "saml_acs_url",
                "https://idp.example.com/acs",
                "SAML ACS URL",
                None,
                "https://idp.example.com/acs",
            ),
            ("saml-x509-cert", "saml_x509_cert", "MIID...cert", "SAML X.509 certificate", None, "masked"),
            (
                "jit-provisioning",
                "jit_provisioning_enabled",
                True,
                "just-in-time provisioning",
                AvailableFeature.AUTOMATIC_PROVISIONING,
                True,
            ),
        ]
    )
    def test_domain_update_activity_logging(
        self, domain_prefix, field, value, expected_field_name, required_feature, expected_logged_value
    ):
        if required_feature:
            self.organization.available_product_features = [{"key": required_feature, "name": required_feature}]
            self.organization.save()

        domain = self._create_verified_domain(f"{domain_prefix}.example.com")

        response = self.client.patch(
            f"/api/organizations/@current/domains/{domain.id}/",
            {field: value},
        )
        self.assertEqual(response.status_code, 200)

        log = ActivityLog.objects.filter(
            organization_id=self.organization.id,
            scope="OrganizationDomain",
            activity="updated",
        ).first()

        assert log is not None
        assert log.detail is not None
        changes = log.detail.get("changes", [])
        field_change = next((c for c in changes if c["field"] == expected_field_name), None)
        assert field_change is not None, f"Expected change for '{expected_field_name}' not found in {changes}"
        self.assertEqual(field_change["after"], expected_logged_value)

    @patch("posthog.models.organization_domain.dns.resolver.resolve")
    def test_domain_verification_activity_logging(self, mock_dns_query):
        response = self.client.post(
            "/api/organizations/@current/domains/",
            {"domain": "verify.example.com"},
        )
        self.assertEqual(response.status_code, 201)
        domain = OrganizationDomain.objects.get(id=response.json()["id"])
        ActivityLog.objects.filter(
            organization_id=self.organization.id,
            scope="OrganizationDomain",
        ).delete()

        mock_dns_query.return_value = FakeDNSResponse(
            [
                dns.rrset.from_text(
                    "_posthog-challenge.verify.example.com.",
                    3600,
                    "IN",
                    "TXT",
                    domain.verification_challenge,
                )
            ]
        )

        with freeze_time("2024-01-15T12:00:00Z"):
            response = self.client.post(f"/api/organizations/@current/domains/{domain.id}/verify")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["is_verified"])

        log = ActivityLog.objects.filter(
            organization_id=self.organization.id,
            scope="OrganizationDomain",
            activity="updated",
        ).first()

        assert log is not None
        assert log.detail is not None
        changes = log.detail.get("changes", [])
        verified_change = next((c for c in changes if c["field"] == "domain verification"), None)
        assert verified_change is not None, f"Expected 'domain verification' change not found in {changes}"

    @patch("posthog.models.organization_domain.dns.resolver.resolve")
    def test_failed_verification_excludes_last_verification_retry(self, mock_dns_query):
        response = self.client.post(
            "/api/organizations/@current/domains/",
            {"domain": "fail-verify.example.com"},
        )
        self.assertEqual(response.status_code, 201)
        domain = OrganizationDomain.objects.get(id=response.json()["id"])
        ActivityLog.objects.filter(
            organization_id=self.organization.id,
            scope="OrganizationDomain",
        ).delete()

        mock_dns_query.side_effect = dns.resolver.NoAnswer()

        response = self.client.post(f"/api/organizations/@current/domains/{domain.id}/verify")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["is_verified"])

        logs = ActivityLog.objects.filter(
            organization_id=self.organization.id,
            scope="OrganizationDomain",
            activity="updated",
        )
        for log in logs:
            assert log.detail is not None
            changes = log.detail.get("changes", [])
            retry_change = next((c for c in changes if c["field"] == "last_verification_retry"), None)
            assert retry_change is None, "last_verification_retry should be excluded from activity logs"
