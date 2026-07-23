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
    def test_find_enforced_org_without_verified_email_domain(
        self, _mock_providers, _name, sso_enforcement, licensed, email, expect_blocked
    ):
        org = self._org_with_domain(sso_enforcement=sso_enforcement, licensed=licensed)
        result = OrganizationDomain.objects.find_enforced_org_without_verified_email_domain(email, [org])
        self.assertEqual(result, org if expect_blocked else None)

    def test_find_enforced_org_scans_all_memberships(self, _mock_providers):
        unenforced = Organization.objects.create(name="Open org")
        enforced = self._org_with_domain()
        # A member of both orgs whose gmail domain is only unverified in the enforcing one is still blocked.
        result = OrganizationDomain.objects.find_enforced_org_without_verified_email_domain(
            "outsider@gmail.com", [unenforced, enforced]
        )
        self.assertEqual(result, enforced)

    def test_get_active_sso_enforcement_for_organization_returns_provider(self, _mock_providers):
        org = self._org_with_domain(sso_enforcement="github")
        self.assertEqual(OrganizationDomain.objects.get_active_sso_enforcement_for_organization(org), "github")

    def test_get_active_sso_enforcement_ignores_unlicensed_org(self, _mock_providers):
        org = self._org_with_domain(licensed=False)
        self.assertIsNone(OrganizationDomain.objects.get_active_sso_enforcement_for_organization(org))
