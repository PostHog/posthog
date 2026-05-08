from posthog.test.base import APIBaseTest, BaseTest
from unittest.mock import patch

from django.test import override_settings

from rest_framework import status

from posthog.models import Organization, User
from posthog.models.organization import OrganizationMembership


@override_settings(CLOUD_DEPLOYMENT="US")
class TestSyncBillingOnMembershipRemoval(BaseTest):
    @patch("posthog.tasks.sync_billing.sync_members_to_billing.delay")
    def test_membership_deletion_triggers_billing_sync(self, mock_delay):
        membership = OrganizationMembership.objects.get(user=self.user, organization=self.organization)
        org_id = str(self.organization.id)

        with self.captureOnCommitCallbacks(execute=True):
            membership.delete()

        mock_delay.assert_called_with(org_id)

    @patch("posthog.tasks.sync_billing.sync_members_to_billing.delay")
    def test_queryset_deletion_triggers_billing_sync(self, mock_delay):
        org_id = str(self.organization.id)

        with self.captureOnCommitCallbacks(execute=True):
            OrganizationMembership.objects.filter(user=self.user, organization=self.organization).delete()

        mock_delay.assert_called_with(org_id)

    @patch("posthog.tasks.sync_billing.sync_members_to_billing.delay")
    @override_settings(CLOUD_DEPLOYMENT=None)
    def test_no_billing_sync_when_not_cloud(self, mock_delay):
        membership = OrganizationMembership.objects.get(user=self.user, organization=self.organization)

        with self.captureOnCommitCallbacks(execute=True):
            membership.delete()

        mock_delay.assert_not_called()

    @patch("posthog.tasks.sync_billing.sync_members_to_billing.delay")
    def test_user_deletion_triggers_billing_sync_for_each_org(self, mock_delay):
        other_org = Organization.objects.create(name="Other Org")
        OrganizationMembership.objects.create(user=self.user, organization=other_org, level=1)

        org_ids = {str(self.organization.id), str(other_org.id)}

        with self.captureOnCommitCallbacks(execute=True):
            self.user.delete()

        synced_org_ids = {c.args[0] for c in mock_delay.call_args_list}
        assert org_ids.issubset(synced_org_ids)

    @patch("posthog.tasks.sync_billing.sync_members_to_billing.delay")
    def test_org_deletion_does_not_sync(self, mock_delay):
        with self.captureOnCommitCallbacks(execute=True):
            self.organization.delete()

        mock_delay.assert_not_called()


@override_settings(CLOUD_DEPLOYMENT="US")
class TestSyncBillingOnMembershipSave(BaseTest):
    @patch("posthog.tasks.sync_billing.sync_members_to_billing.delay")
    def test_membership_creation_triggers_billing_sync(self, mock_delay):
        # Covers Organization.bootstrap, Vercel integration, and any other path
        # that creates OrganizationMembership directly (bypassing User.join).
        other_org = Organization.objects.create(name="Bootstrap Org")
        mock_delay.reset_mock()

        with self.captureOnCommitCallbacks(execute=True):
            OrganizationMembership.objects.create(
                user=self.user, organization=other_org, level=OrganizationMembership.Level.OWNER
            )

        mock_delay.assert_called_once_with(str(other_org.id))

    @patch("posthog.tasks.sync_billing.sync_members_to_billing.delay")
    def test_membership_level_change_triggers_billing_sync(self, mock_delay):
        # Covers direct ORM level changes that bypass OrganizationMemberSerializer,
        # e.g. the Vercel integration's _add_user_to_organization level bump.
        membership = OrganizationMembership.objects.get(user=self.user, organization=self.organization)
        mock_delay.reset_mock()

        with self.captureOnCommitCallbacks(execute=True):
            membership.level = OrganizationMembership.Level.ADMIN
            membership.save(update_fields=["level"])

        mock_delay.assert_called_once_with(str(self.organization.id))

    @patch("posthog.tasks.sync_billing.sync_members_to_billing.delay")
    def test_membership_save_without_level_change_does_not_sync(self, mock_delay):
        membership = OrganizationMembership.objects.get(user=self.user, organization=self.organization)
        mock_delay.reset_mock()

        with self.captureOnCommitCallbacks(execute=True):
            membership.save()

        mock_delay.assert_not_called()

    @patch("posthog.tasks.sync_billing.sync_members_to_billing.delay")
    @override_settings(CLOUD_DEPLOYMENT=None)
    def test_no_billing_sync_when_not_cloud_on_save(self, mock_delay):
        other_org = Organization.objects.create(name="Non-cloud Org")
        mock_delay.reset_mock()

        with self.captureOnCommitCallbacks(execute=True):
            OrganizationMembership.objects.create(
                user=self.user, organization=other_org, level=OrganizationMembership.Level.OWNER
            )

        mock_delay.assert_not_called()


@override_settings(CLOUD_DEPLOYMENT="US")
class TestSyncBillingFlows(APIBaseTest):
    """End-to-end flow coverage: each user-level operation must trigger the signal-driven sync."""

    @patch("posthog.tasks.sync_billing.sync_members_to_billing.delay")
    def test_user_join_triggers_billing_sync(self, mock_delay):
        other_org = Organization.objects.create(name="Joinable Org")
        mock_delay.reset_mock()

        with self.captureOnCommitCallbacks(execute=True):
            self.user.join(organization=other_org, level=OrganizationMembership.Level.MEMBER)

        mock_delay.assert_called_once_with(str(other_org.id))

    @patch("posthog.tasks.sync_billing.sync_members_to_billing.delay")
    def test_user_leave_triggers_billing_sync(self, mock_delay):
        other_org = Organization.objects.create(name="Leavable Org")
        OrganizationMembership.objects.create(
            user=self.user, organization=other_org, level=OrganizationMembership.Level.OWNER
        )
        member = User.objects.create_and_join(other_org, "leaver@x.com", None, "X")
        mock_delay.reset_mock()

        with self.captureOnCommitCallbacks(execute=True):
            member.leave(organization=other_org)

        mock_delay.assert_called_once_with(str(other_org.id))

    @patch("posthog.tasks.sync_billing.sync_members_to_billing.delay")
    def test_api_member_level_change_triggers_billing_sync(self, mock_delay):
        member = User.objects.create_and_join(self.organization, "promotable@x.com", None, "X")
        self.organization_membership.level = OrganizationMembership.Level.OWNER
        self.organization_membership.save()
        mock_delay.reset_mock()

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.patch(
                f"/api/organizations/@current/members/{member.uuid}/",
                {"level": OrganizationMembership.Level.ADMIN.value},
            )

        assert response.status_code == status.HTTP_200_OK
        mock_delay.assert_called_once_with(str(self.organization.id))

    @patch("posthog.tasks.sync_billing.sync_members_to_billing.delay")
    def test_api_member_delete_triggers_billing_sync(self, mock_delay):
        member = User.objects.create_and_join(self.organization, "removable@x.com", None, "X")
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        mock_delay.reset_mock()

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.delete(f"/api/organizations/@current/members/{member.uuid}/")

        assert response.status_code == status.HTTP_204_NO_CONTENT
        mock_delay.assert_called_once_with(str(self.organization.id))
