from posthog.test.base import BaseTest
from unittest.mock import patch

from django.test import override_settings

from posthog.models import Organization
from posthog.models.organization import OrganizationMembership


@override_settings(CLOUD_DEPLOYMENT="US")
class TestSyncBillingOnMembershipRemoval(BaseTest):
    @patch("posthog.tasks.sync_billing.sync_members_to_billing.delay")
    @patch("django.db.transaction.on_commit", side_effect=lambda f: f())
    def test_membership_deletion_triggers_billing_sync(self, _mock_on_commit, mock_delay):
        membership = OrganizationMembership.objects.get(user=self.user, organization=self.organization)
        org_id = str(self.organization.id)

        membership.delete()

        mock_delay.assert_called_with(org_id)

    @patch("posthog.tasks.sync_billing.sync_members_to_billing.delay")
    @patch("django.db.transaction.on_commit", side_effect=lambda f: f())
    def test_queryset_deletion_triggers_billing_sync(self, _mock_on_commit, mock_delay):
        org_id = str(self.organization.id)

        OrganizationMembership.objects.filter(user=self.user, organization=self.organization).delete()

        mock_delay.assert_called_with(org_id)

    @patch("posthog.tasks.sync_billing.sync_members_to_billing.delay")
    @patch("django.db.transaction.on_commit", side_effect=lambda f: f())
    @override_settings(CLOUD_DEPLOYMENT=None)
    def test_no_billing_sync_when_not_cloud(self, _mock_on_commit, mock_delay):
        membership = OrganizationMembership.objects.get(user=self.user, organization=self.organization)
        membership.delete()

        mock_delay.assert_not_called()

    @patch("posthog.tasks.sync_billing.sync_members_to_billing.delay")
    @patch("django.db.transaction.on_commit", side_effect=lambda f: f())
    def test_user_deletion_triggers_billing_sync_for_each_org(self, _mock_on_commit, mock_delay):
        other_org = Organization.objects.create(name="Other Org")
        OrganizationMembership.objects.create(user=self.user, organization=other_org, level=1)

        org_ids = {str(self.organization.id), str(other_org.id)}

        self.user.delete()

        synced_org_ids = {c.args[0] for c in mock_delay.call_args_list}
        assert org_ids.issubset(synced_org_ids)

    @patch("posthog.tasks.sync_billing.sync_members_to_billing.delay")
    def test_org_deletion_does_not_sync(self, mock_delay):
        callbacks: list = []
        with patch("django.db.transaction.on_commit", side_effect=lambda f: callbacks.append(f)):
            self.organization.delete()

        # Run callbacks after deletion completes (simulates post-commit)
        for cb in callbacks:
            cb()

        mock_delay.assert_not_called()
