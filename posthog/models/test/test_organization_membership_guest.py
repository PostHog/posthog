from posthog.test.base import BaseTest

from posthog.models.organization import OrganizationMembership
from posthog.models.user import User


class TestOrganizationMembershipGuest(BaseTest):
    def test_is_guest_defaults_to_false(self):
        user = User.objects.create_user(email="regular@posthog.com", password="x", first_name="Regular")
        membership = OrganizationMembership.objects.create(organization=self.organization, user=user)
        self.assertFalse(membership.is_guest)

    def test_is_guest_can_be_set_to_true(self):
        user = User.objects.create_user(email="guest@posthog.com", password="x", first_name="Guest")
        membership = OrganizationMembership.objects.create(organization=self.organization, user=user, is_guest=True)
        self.assertTrue(membership.is_guest)

    def test_bypass_sso_enforcement_defaults_to_false(self):
        user = User.objects.create_user(email="g1@posthog.com", password="x", first_name="G1")
        membership = OrganizationMembership.objects.create(organization=self.organization, user=user)
        self.assertFalse(membership.bypass_sso_enforcement)

    def test_bypass_sso_enforcement_can_be_set_on_guest(self):
        user = User.objects.create_user(email="g2@posthog.com", password="x", first_name="G2")
        membership = OrganizationMembership.objects.create(
            organization=self.organization, user=user, is_guest=True, bypass_sso_enforcement=True
        )
        self.assertTrue(membership.bypass_sso_enforcement)
