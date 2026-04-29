"""Cross-org semantics for OrganizationMembership.bypass_sso.

Bypass is carved out by the admin of the org that owns the SSO-enforcing domain.
A bypass membership in a *different* org must not override that enforcement —
otherwise Org B's admin could grant an SSO exception that leaks into Org A's
security posture.
"""

from posthog.test.base import APIBaseTest

from django.utils import timezone

from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models import User
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.organization_domain import OrganizationDomain

VALID_PASSWORD = "mighty-strong-secure-1337!!"


class TestSsoBypass(APIBaseTest):
    """Covers the per-membership SSO bypass honored by the /api/login endpoint.

    Test matrix (shared domain `bypasscorp.example`, enforcement owned by self.organization):
      1. No bypass → password login rejected.
      2. Bypass on membership in the enforcing org → password login allowed.
      3. Bypass on membership in a DIFFERENT org → password login still rejected.
    """

    def setUp(self) -> None:
        super().setUp()
        self.organization.available_product_features = [
            {"key": AvailableFeature.SSO_ENFORCEMENT, "name": "SSO enforcement"},
        ]
        self.organization.save()
        OrganizationDomain.objects.create(
            domain="bypasscorp.example",
            organization=self.organization,
            verified_at=timezone.now(),
            sso_enforcement="google-oauth2",
        )

    def _create_test_user(self, email: str, organization: Organization, *, bypass_sso: bool = False) -> User:
        user = User.objects.create_user(email=email, first_name="Test", password=VALID_PASSWORD)
        OrganizationMembership.objects.create(organization=organization, user=user, bypass_sso=bypass_sso)
        return user

    def test_password_login_rejected_for_enforced_domain_without_bypass(self) -> None:
        self._create_test_user("regular@bypasscorp.example", self.organization)
        res = self.client.post("/api/login", {"email": "regular@bypasscorp.example", "password": VALID_PASSWORD})
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.json()["code"], "sso_enforced")

    def test_password_login_allowed_with_bypass_in_enforcing_org(self) -> None:
        self._create_test_user("guest@bypasscorp.example", self.organization, bypass_sso=True)
        res = self.client.post("/api/login", {"email": "guest@bypasscorp.example", "password": VALID_PASSWORD})
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.content)

    def test_password_login_rejected_for_bypass_in_different_org(self) -> None:
        # User is a bypass-enabled guest in Org B, but their email domain is enforced by
        # Org A (self.organization). Bypass in Org B must not let them skip Org A's enforcement.
        other_org = Organization.objects.create(name="Org B")
        user = self._create_test_user("outsider@bypasscorp.example", other_org, bypass_sso=True)
        # Also give them a regular (non-bypass) membership in the enforcing org, mirroring a
        # real-world case where the user belongs to both orgs.
        OrganizationMembership.objects.create(organization=self.organization, user=user, bypass_sso=False)

        res = self.client.post("/api/login", {"email": "outsider@bypasscorp.example", "password": VALID_PASSWORD})
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.json()["code"], "sso_enforced")

    def test_password_login_works_on_unenforced_domain_regardless_of_bypass(self) -> None:
        # Sanity check: bypass_sso is a no-op when the email's domain isn't SSO-enforced.
        self._create_test_user("normal@other.example", self.organization)
        res = self.client.post("/api/login", {"email": "normal@other.example", "password": VALID_PASSWORD})
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.content)
