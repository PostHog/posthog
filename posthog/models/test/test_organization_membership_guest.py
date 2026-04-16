from posthog.test.base import BaseTest

from posthog.models.activity_logging.activity_log import ActivityLog
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

    def test_objects_manager_includes_guests(self):
        regular_user = User.objects.create_user(email="r@posthog.com", password="x", first_name="R")
        guest_user = User.objects.create_user(email="g@posthog.com", password="x", first_name="G")
        OrganizationMembership.objects.create(organization=self.organization, user=regular_user)
        OrganizationMembership.objects.create(organization=self.organization, user=guest_user, is_guest=True)
        # Default manager includes both
        self.assertTrue(OrganizationMembership.objects.filter(user=regular_user).exists())
        self.assertTrue(OrganizationMembership.objects.filter(user=guest_user).exists())

    def test_regular_manager_excludes_guests(self):
        regular_user = User.objects.create_user(email="r2@posthog.com", password="x", first_name="R2")
        guest_user = User.objects.create_user(email="g2@posthog.com", password="x", first_name="G2")
        OrganizationMembership.objects.create(organization=self.organization, user=regular_user)
        OrganizationMembership.objects.create(organization=self.organization, user=guest_user, is_guest=True)
        self.assertTrue(OrganizationMembership.regular.filter(user=regular_user).exists())
        self.assertFalse(OrganizationMembership.regular.filter(user=guest_user).exists())

    def test_is_guest_change_emits_activity_log(self):
        user = User.objects.create_user(email="promote@posthog.com", password="x", first_name="P")
        membership = OrganizationMembership.objects.create(organization=self.organization, user=user, is_guest=True)
        # Clear any create entries
        ActivityLog.objects.filter(scope="OrganizationMembership", item_id=str(membership.id)).delete()

        membership.is_guest = False
        membership.save()

        self.assertTrue(
            ActivityLog.objects.filter(
                scope="OrganizationMembership", activity="updated", item_id=str(membership.id)
            ).exists()
        )
