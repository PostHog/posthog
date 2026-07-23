from posthog.test.base import BaseTest
from unittest import mock

from django.utils import timezone

from parameterized import parameterized

from posthog.constants import AvailableFeature
from posthog.models import Organization, OrganizationDomain

SSO_PROVIDERS = {"google-oauth2": True, "github": True, "gitlab": True}


@mock.patch("posthog.models.organization_domain.get_instance_available_sso_providers", return_value=SSO_PROVIDERS)
class TestOrganizationDomainSSOEnforcement(BaseTest):
    def _org_with_domain(self, *, sso_enforcement: str = "google-oauth2", licensed: bool = True) -> Organization:
        org = Organization.objects.create(name="Enforced org")
        if licensed:
            org.available_product_features = [
                {"key": AvailableFeature.SSO_ENFORCEMENT, "name": AvailableFeature.SSO_ENFORCEMENT}
            ]
            org.save()
        OrganizationDomain.objects.create(
            domain="hogflix.posthog.com",
            organization=org,
            sso_enforcement=sso_enforcement,
            verified_at=timezone.now(),
        )
        return org

    @parameterized.expand(
        [
            # (name, sso_enforcement, licensed, email, expect_blocked)
            ("blocks_domain_not_verified_for_org", "google-oauth2", True, "outsider@gmail.com", True),
            ("allows_verified_domain", "google-oauth2", True, "insider@hogflix.posthog.com", False),
            ("allows_when_enforcement_unlicensed", "google-oauth2", False, "outsider@gmail.com", False),
            ("allows_when_org_does_not_enforce", "", True, "outsider@gmail.com", False),
        ]
    )
    def test_is_email_blocked_by_sso_enforcement(
        self, _mock_providers, _name, sso_enforcement, licensed, email, expect_blocked
    ):
        org = self._org_with_domain(sso_enforcement=sso_enforcement, licensed=licensed)
        self.assertEqual(OrganizationDomain.objects.is_email_blocked_by_sso_enforcement(email, org), expect_blocked)

    def test_email_on_any_verified_domain_is_allowed(self, _mock_providers):
        # Enforcement gates on the org, but the allow-list is all of the org's verified domains —
        # not just the enforcing one. Multi-domain orgs must accept invitees from every verified domain.
        org = self._org_with_domain()
        OrganizationDomain.objects.create(domain="hogflix.dev", organization=org, verified_at=timezone.now())
        self.assertFalse(OrganizationDomain.objects.is_email_blocked_by_sso_enforcement("x@hogflix.dev", org))
        self.assertTrue(OrganizationDomain.objects.is_email_blocked_by_sso_enforcement("x@gmail.com", org))

    def test_get_active_sso_enforcement_for_organization_returns_provider(self, _mock_providers):
        org = self._org_with_domain(sso_enforcement="github")
        self.assertEqual(OrganizationDomain.objects.get_active_sso_enforcement_for_organization(org), "github")

    def test_get_active_sso_enforcement_ignores_unlicensed_org(self, _mock_providers):
        org = self._org_with_domain(licensed=False)
        self.assertIsNone(OrganizationDomain.objects.get_active_sso_enforcement_for_organization(org))
