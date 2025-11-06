from datetime import timedelta

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.utils import timezone

from posthog.models import OrganizationInvite
from posthog.models.organization import OrganizationMembership
from posthog.models.team.team import Team
from posthog.models.user import User

from products.enterprise.backend.models.explicit_team_membership import ExplicitTeamMembership
from products.enterprise.backend.models.rbac.access_control import AccessControl


class TestOrganizationInvite(BaseTest):
    def test_organization_active_invites(self):
        """Test that active invites are correctly identified based on creation date"""
        self.assertEqual(self.organization.invites.count(), 0)
        self.assertEqual(self.organization.active_invites.count(), 0)

        OrganizationInvite.objects.create(organization=self.organization)
        self.assertEqual(self.organization.invites.count(), 1)
        self.assertEqual(self.organization.active_invites.count(), 1)

        expired_invite = OrganizationInvite.objects.create(organization=self.organization)
        OrganizationInvite.objects.filter(id=expired_invite.id).update(created_at=timezone.now() - timedelta(hours=73))
        self.assertEqual(self.organization.invites.count(), 2)
        self.assertEqual(self.organization.active_invites.count(), 1)

    def test_invite_use_with_new_access_control_admin(self):
        """Test using an invite with the new access control system for admin level"""
        team = Team.objects.create(organization=self.organization, name="New Team")

        # Create a user who will use the invite
        user = User.objects.create_user(email="test@posthog.com", password="password", first_name="first_name")

        # Create an invite with private project access
        invite = OrganizationInvite.objects.create(
            organization=self.organization,
            target_email="test@posthog.com",
            private_project_access=[{"id": team.id, "level": "admin"}],
        )

        # Use the invite
        invite.use(user, prevalidated=True)

        # Verify the user has been added to the organization
        org_membership = OrganizationMembership.objects.filter(organization=self.organization, user=user).first()
        self.assertIsNotNone(org_membership)

        # Verify the access control has been created correctly
        access_control = AccessControl.objects.filter(
            team=team, resource="project", resource_id=str(team.id), organization_member=org_membership
        ).first()
        if not access_control:
            raise Exception("Access control not found")

        self.assertEqual(access_control.access_level, "admin")

        # Verify the invite has been deleted
        self.assertFalse(OrganizationInvite.objects.filter(target_email="test@posthog.com").exists())

    def test_invite_use_with_new_access_control_member(self):
        """Test using an invite with the new access control system for member level"""
        team = Team.objects.create(organization=self.organization, name="New Team 2")

        # Create a user who will use the invite
        user = User.objects.create_user(email="test2@posthog.com", password="password", first_name="first_name")

        # Create an invite with private project access
        invite = OrganizationInvite.objects.create(
            organization=self.organization,
            target_email="test2@posthog.com",
            private_project_access=[{"id": team.id, "level": "member"}],
        )

        # Use the invite
        invite.use(user, prevalidated=True)

        # Verify the user has been added to the organization
        org_membership = OrganizationMembership.objects.filter(organization=self.organization, user=user).first()
        self.assertIsNotNone(org_membership)

        # Verify the access control has been created with member level
        access_control = AccessControl.objects.filter(
            team=team, resource="project", resource_id=str(team.id), organization_member=org_membership
        ).first()

        if not access_control:
            raise Exception("Access control not found")

        self.assertEqual(access_control.access_level, "member")

        # Verify the invite has been deleted
        self.assertFalse(OrganizationInvite.objects.filter(target_email="test2@posthog.com").exists())

    def test_invite_use_with_nonexistent_team(self):
        """Test using an invite with a team that no longer exists"""
        # Create a user who will use the invite
        user = User.objects.create_user(email="nonexistent@posthog.com", password="password", first_name="first_name")

        # Create an invite with private project access to a non-existent team ID
        invite = OrganizationInvite.objects.create(
            organization=self.organization,
            target_email="nonexistent@posthog.com",
            private_project_access=[{"id": 99999, "level": "admin"}],
        )

        # Use the invite - this should not raise an exception
        invite.use(user, prevalidated=True)

        # Verify the user has been added to the organization
        org_membership = OrganizationMembership.objects.filter(organization=self.organization, user=user).first()
        self.assertIsNotNone(org_membership)

        # Verify the invite has been deleted
        self.assertFalse(OrganizationInvite.objects.filter(target_email="nonexistent@posthog.com").exists())

    @patch("posthog.models.organization_invite.is_email_available")
    @patch("posthog.tasks.email.send_member_join.apply_async")
    def test_invite_use_sends_email_notification(self, mock_send_email, mock_is_email_available):
        """Test that using an invite sends an email notification when configured"""
        mock_is_email_available.return_value = True

        # Set organization to enable member join emails
        self.organization.is_member_join_email_enabled = True
        self.organization.save()

        # Create a user who will use the invite
        user = User.objects.create_user(email="email_test@posthog.com", password="password", first_name="first_name")

        # Create an invite
        invite = OrganizationInvite.objects.create(
            organization=self.organization, target_email="email_test@posthog.com"
        )

        # Use the invite
        invite.use(user, prevalidated=True)

        # Verify the email task was called
        mock_send_email.assert_called_once_with(
            kwargs={
                "invitee_uuid": user.uuid,
                "organization_id": self.organization.id,
            }
        )

    def test_invite_use_without_private_project_access(self):
        """Test using an invite without private project access returns early"""
        # Create a user who will use the invite
        user = User.objects.create_user(email="no_access@posthog.com", password="password", first_name="first_name")

        # Create an invite without private project access
        invite = OrganizationInvite.objects.create(
            organization=self.organization,
            target_email="no_access@posthog.com",
            private_project_access=None,
        )

        # Use the invite
        invite.use(user, prevalidated=True)

        # Verify the user has been added to the organization
        org_membership = OrganizationMembership.objects.filter(organization=self.organization, user=user).first()
        self.assertIsNotNone(org_membership)

        # Verify no explicit team memberships were created
        self.assertEqual(ExplicitTeamMembership.objects.filter(parent_membership=org_membership).count(), 0)

        # Verify no access controls were created
        self.assertEqual(AccessControl.objects.filter(organization_member=org_membership).count(), 0)

        # Verify the invite has been deleted
        self.assertFalse(OrganizationInvite.objects.filter(target_email="no_access@posthog.com").exists())

    def test_invite_use_only_deletes_organization_specific_invites(self):
        """Test that using an invite only deletes invites for the specific organization, not all organizations"""
        from posthog.models import Organization

        # Create a second organization
        second_org = Organization.objects.create(name="Second Org")

        # Create a user who will use the invite
        user = User.objects.create_user(email="cross_org@posthog.com", password="password", first_name="Test")

        # Create invites with the same email in both organizations
        invite_org1 = OrganizationInvite.objects.create(
            organization=self.organization,
            target_email="cross_org@posthog.com",
        )
        invite_org2 = OrganizationInvite.objects.create(
            organization=second_org,
            target_email="cross_org@posthog.com",
        )

        # Verify both invites exist before using one
        self.assertTrue(OrganizationInvite.objects.filter(id=invite_org1.id).exists())
        self.assertTrue(OrganizationInvite.objects.filter(id=invite_org2.id).exists())

        # Use the invite for the first organization
        invite_org1.use(user, prevalidated=True)

        # Verify the user has been added to the first organization
        org_membership = OrganizationMembership.objects.filter(organization=self.organization, user=user).first()
        self.assertIsNotNone(org_membership)

        # Verify the invite for the first organization has been deleted
        self.assertFalse(OrganizationInvite.objects.filter(id=invite_org1.id).exists())

        # Verify the invite for the second organization still exists
        self.assertTrue(OrganizationInvite.objects.filter(id=invite_org2.id).exists())

        # Clean up
        second_org.delete()
