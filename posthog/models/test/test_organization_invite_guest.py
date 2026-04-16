from posthog.test.base import BaseTest

from posthog.models import OrganizationInvite


class TestOrganizationInviteGuest(BaseTest):
    def test_is_guest_defaults_to_false(self):
        invite = OrganizationInvite.objects.create(organization=self.organization, target_email="new@posthog.com")
        self.assertFalse(invite.is_guest)
        self.assertFalse(invite.bypass_sso_enforcement)

    def test_is_guest_can_be_set_with_bypass(self):
        invite = OrganizationInvite.objects.create(
            organization=self.organization,
            target_email="new2@posthog.com",
            is_guest=True,
            bypass_sso_enforcement=True,
        )
        self.assertTrue(invite.is_guest)
        self.assertTrue(invite.bypass_sso_enforcement)
