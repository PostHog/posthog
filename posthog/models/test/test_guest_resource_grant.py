from posthog.test.base import BaseTest

from posthog.models import GuestResourceGrant, OrganizationInvite, OrganizationMembership, User


class TestGuestResourceGrant(BaseTest):
    def _make_guest_membership(self, email: str = "guest@posthog.com") -> OrganizationMembership:
        user = User.objects.create_user(email=email, password="x", first_name="Guest")
        return OrganizationMembership.objects.create(organization=self.organization, user=user, is_guest=True)

    def test_create_active_grant_on_membership(self):
        membership = self._make_guest_membership()
        grant = GuestResourceGrant.objects.create(
            organization_membership=membership,
            team=self.team,
            resource=GuestResourceGrant.Resource.DASHBOARD,
            resource_id=1,
            is_pending=False,
            created_by=self.user,
        )
        self.assertFalse(grant.is_pending)
        self.assertEqual(grant.resource, "dashboard")
        self.assertIsNone(grant.invite)

    def test_create_pending_grant_on_invite(self):
        invite = OrganizationInvite.objects.create(
            organization=self.organization, target_email="new@posthog.com", is_guest=True
        )
        grant = GuestResourceGrant.objects.create(
            invite=invite,
            team=self.team,
            resource=GuestResourceGrant.Resource.NOTEBOOK,
            resource_id=42,
            is_pending=True,
            created_by=self.user,
        )
        self.assertTrue(grant.is_pending)
        self.assertIsNone(grant.organization_membership)

    def test_activity_scope_is_registered(self):
        from typing import get_args

        from posthog.models.activity_logging.activity_log import ActivityScope

        self.assertIn("GuestResourceGrant", get_args(ActivityScope))
