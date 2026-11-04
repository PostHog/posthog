from posthog.test.base import BaseTest

from django.utils import timezone

from parameterized import parameterized

from posthog.models import Organization, OrganizationDomain


class TestOrganizationDomainEnforcement(BaseTest):
    def _org_with_domain(self, *, enforce: bool = True) -> Organization:
        org = Organization.objects.create(name="Enforced org", enforce_verified_domains=enforce)
        OrganizationDomain.objects.create(
            domain="hogflix.posthog.com",
            organization=org,
            verified_at=timezone.now(),
        )
        return org

    @parameterized.expand(
        [
            # (name, enforce, email, expect_blocked)
            ("blocks_domain_not_verified_for_org", True, "outsider@gmail.com", True),
            ("allows_verified_domain", True, "insider@hogflix.posthog.com", False),
            ("allows_when_setting_off", False, "outsider@gmail.com", False),
        ]
    )
    def test_is_email_blocked_by_domain_enforcement(self, _name, enforce, email, expect_blocked):
        org = self._org_with_domain(enforce=enforce)
        self.assertEqual(OrganizationDomain.objects.is_email_blocked_by_domain_enforcement(email, org), expect_blocked)

    def test_email_on_any_verified_domain_is_allowed(self):
        # The allow-list is all of the org's verified domains — multi-domain orgs must accept
        # emails from every verified domain.
        org = self._org_with_domain()
        OrganizationDomain.objects.create(domain="hogflix.dev", organization=org, verified_at=timezone.now())
        self.assertFalse(OrganizationDomain.objects.is_email_blocked_by_domain_enforcement("x@hogflix.dev", org))
        self.assertTrue(OrganizationDomain.objects.is_email_blocked_by_domain_enforcement("x@gmail.com", org))

    def test_unverified_domain_does_not_count(self):
        # A pending (unverified) domain must not satisfy the allow-list.
        org = self._org_with_domain()
        OrganizationDomain.objects.create(domain="pending.example.com", organization=org, verified_at=None)
        self.assertTrue(OrganizationDomain.objects.is_email_blocked_by_domain_enforcement("x@pending.example.com", org))


class TestTheDomainOfAnEmailAddress(BaseTest):
    QUOTED_LOCAL_PART = '"x@y"@hogflix.posthog.com'

    def _verified_domain(self) -> Organization:
        organization = Organization.objects.create(name="Hogflix", enforce_verified_domains=True)
        OrganizationDomain.objects.create(
            domain="hogflix.posthog.com",
            organization=organization,
            verified_at=timezone.now(),
        )
        return organization

    @parameterized.expand(
        [
            ("plain", "insider@hogflix.posthog.com"),
            ("quoted_local_part_holding_an_at", QUOTED_LOCAL_PART),
        ]
    )
    def test_a_verified_domain_admits_the_address(self, _name: str, email: str) -> None:
        organization = self._verified_domain()

        self.assertTrue(OrganizationDomain.objects.is_domain_verified_for_organization(email, organization))
        self.assertFalse(OrganizationDomain.objects.is_email_blocked_by_domain_enforcement(email, organization))
        self.assertIsNotNone(OrganizationDomain.objects.get_verified_for_email_address(email))

    @parameterized.expand([("no_at", "nobody"), ("empty_domain", "nobody@"), ("empty", "")])
    def test_an_address_without_a_domain_matches_nothing(self, _name: str, email: str) -> None:
        organization = self._verified_domain()

        self.assertIsNone(OrganizationDomain.objects.get_verified_for_email_address(email))
        self.assertIsNone(OrganizationDomain.objects.get_sso_enforcement_for_email_address(email))
        self.assertFalse(OrganizationDomain.objects.is_domain_verified_for_organization(email, organization))
