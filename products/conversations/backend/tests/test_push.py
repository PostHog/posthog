from posthog.test.base import BaseTest
from unittest.mock import patch

from posthog.models import Organization, OrganizationMembership, Team, User

from products.conversations.backend.push import push_unread_count_changed


class TestPushUnreadCountChanged(BaseTest):
    def setUp(self):
        super().setUp()
        self.organization = Organization.objects.create(name="Push Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Push Test Team")
        self.user1 = User.objects.create_and_join(self.organization, "push1@test.com", "password")
        self.user2 = User.objects.create_and_join(self.organization, "push2@test.com", "password")

    @patch("products.conversations.backend.push.publish_silent_push")
    def test_publishes_for_all_org_members(self, mock_publish):
        push_unread_count_changed(self.team)

        mock_publish.assert_called_once()
        call_kwargs = mock_publish.call_args[1]
        assert call_kwargs["organization_id"] == str(self.organization.id)
        assert call_kwargs["team_id"] == self.team.pk
        assert call_kwargs["event_type"] == "conversations_unread_changed"
        assert set(call_kwargs["user_ids"]) == {self.user1.id, self.user2.id}

    @patch("products.conversations.backend.push.publish_silent_push")
    def test_skips_when_no_org_members(self, mock_publish):
        OrganizationMembership.objects.filter(organization=self.organization).delete()
        push_unread_count_changed(self.team)
        mock_publish.assert_not_called()
