from posthog.test.base import BaseTest

from django.db import IntegrityError

from parameterized import parameterized

from posthog.models import GuestResourceGrant, OrganizationInvite, OrganizationMembership, User
from posthog.models.activity_logging.activity_log import ActivityLog


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
            resource_id="1",
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
            resource_id="42",
            is_pending=True,
            created_by=self.user,
        )
        self.assertTrue(grant.is_pending)
        self.assertIsNone(grant.organization_membership)

    @parameterized.expand(
        [
            ("dashboard", GuestResourceGrant.Resource.DASHBOARD),
            ("insight", GuestResourceGrant.Resource.INSIGHT),
            ("notebook", GuestResourceGrant.Resource.NOTEBOOK),
        ]
    )
    def test_active_grant_uniqueness(self, _name, resource):
        membership = self._make_guest_membership(email=f"{_name}@posthog.com")
        GuestResourceGrant.objects.create(
            organization_membership=membership,
            team=self.team,
            resource=resource,
            resource_id="1",
            is_pending=False,
        )
        with self.assertRaises(IntegrityError):
            GuestResourceGrant.objects.create(
                organization_membership=membership,
                team=self.team,
                resource=resource,
                resource_id="1",
                is_pending=False,
            )

    @parameterized.expand(
        [
            ("dashboard", GuestResourceGrant.Resource.DASHBOARD),
            ("insight", GuestResourceGrant.Resource.INSIGHT),
            ("notebook", GuestResourceGrant.Resource.NOTEBOOK),
        ]
    )
    def test_pending_grant_uniqueness_per_invite(self, _name, resource):
        invite = OrganizationInvite.objects.create(
            organization=self.organization, target_email=f"p-{_name}@posthog.com", is_guest=True
        )
        GuestResourceGrant.objects.create(
            invite=invite,
            team=self.team,
            resource=resource,
            resource_id="7",
            is_pending=True,
        )
        with self.assertRaises(IntegrityError):
            GuestResourceGrant.objects.create(
                invite=invite,
                team=self.team,
                resource=resource,
                resource_id="7",
                is_pending=True,
            )

    def test_cannot_create_grant_with_both_fks(self):
        membership = self._make_guest_membership(email="both@posthog.com")
        invite = OrganizationInvite.objects.create(
            organization=self.organization, target_email="both@posthog.com", is_guest=True
        )
        with self.assertRaises(IntegrityError):
            GuestResourceGrant.objects.create(
                organization_membership=membership,
                invite=invite,
                team=self.team,
                resource=GuestResourceGrant.Resource.DASHBOARD,
                resource_id="1",
                is_pending=False,
            )

    def test_cannot_create_grant_with_neither_fk(self):
        with self.assertRaises(IntegrityError):
            GuestResourceGrant.objects.create(
                organization_membership=None,
                invite=None,
                team=self.team,
                resource=GuestResourceGrant.Resource.DASHBOARD,
                resource_id="1",
                is_pending=False,
            )

    def test_cannot_have_pending_with_membership(self):
        membership = self._make_guest_membership(email="mismatch@posthog.com")
        with self.assertRaises(IntegrityError):
            GuestResourceGrant.objects.create(
                organization_membership=membership,
                team=self.team,
                resource=GuestResourceGrant.Resource.DASHBOARD,
                resource_id="1",
                is_pending=True,
            )

    def test_cannot_have_active_with_invite(self):
        invite = OrganizationInvite.objects.create(
            organization=self.organization, target_email="m2@posthog.com", is_guest=True
        )
        with self.assertRaises(IntegrityError):
            GuestResourceGrant.objects.create(
                invite=invite,
                team=self.team,
                resource=GuestResourceGrant.Resource.DASHBOARD,
                resource_id="1",
                is_pending=False,
            )

    def test_grant_flips_from_pending_to_active(self):
        invite = OrganizationInvite.objects.create(
            organization=self.organization, target_email="flip@posthog.com", is_guest=True
        )
        grant = GuestResourceGrant.objects.create(
            invite=invite,
            team=self.team,
            resource=GuestResourceGrant.Resource.DASHBOARD,
            resource_id="9",
            is_pending=True,
        )
        # Simulate accept: create the membership, rebind the grant.
        user = User.objects.create_user(email="flip@posthog.com", password="x", first_name="F")
        membership = OrganizationMembership.objects.create(organization=self.organization, user=user, is_guest=True)
        grant.organization_membership = membership
        grant.invite = None
        grant.is_pending = False
        grant.save()

        grant.refresh_from_db()
        self.assertFalse(grant.is_pending)
        self.assertIsNone(grant.invite)
        self.assertEqual(grant.organization_membership, membership)

    def test_crud_emits_activity_log(self):
        membership = self._make_guest_membership(email="act@posthog.com")

        # Create
        grant = GuestResourceGrant.objects.create(
            organization_membership=membership,
            team=self.team,
            resource=GuestResourceGrant.Resource.DASHBOARD,
            resource_id="1",
            is_pending=False,
        )
        self.assertTrue(
            ActivityLog.objects.filter(scope="GuestResourceGrant", activity="created", item_id=str(grant.id)).exists()
        )

        # Update
        grant.resource_id = "2"
        grant.save()
        self.assertTrue(
            ActivityLog.objects.filter(scope="GuestResourceGrant", activity="updated", item_id=str(grant.id)).exists()
        )

        # Delete
        grant_id = str(grant.id)
        grant.delete()
        self.assertTrue(
            ActivityLog.objects.filter(scope="GuestResourceGrant", activity="deleted", item_id=grant_id).exists()
        )
