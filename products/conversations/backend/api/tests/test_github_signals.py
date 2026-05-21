from posthog.test.base import BaseTest
from unittest.mock import patch

from django.db import transaction

from parameterized import parameterized

from posthog.models.comment import Comment

from products.conversations.backend.models import Ticket
from products.conversations.backend.models.constants import Channel


def immediate_on_commit(func):
    func()


@patch.object(transaction, "on_commit", side_effect=immediate_on_commit)
class TestGithubReplySignal(BaseTest):
    def setUp(self):
        super().setUp()
        self.team.conversations_settings = {"github_enabled": True}
        self.team.save()
        self.github_ticket = Ticket.objects.create_with_number(
            team=self.team,
            widget_session_id="",
            distinct_id="github:octocat",
            channel_source=Channel.GITHUB,
            github_repo="org/repo",
            github_issue_number=42,
        )

    @patch("products.conversations.backend.tasks.post_reply_to_github.delay")
    def test_team_message_enqueues_github_reply(self, mock_delay, _mock_on_commit):
        Comment.objects.create(
            team=self.team,
            scope="conversations_ticket",
            item_id=str(self.github_ticket.id),
            content="We are looking into this",
            created_by=self.user,
            item_context={"author_type": "support", "is_private": False},
        )

        mock_delay.assert_called_once()
        call_kwargs = mock_delay.call_args[1]
        assert call_kwargs["ticket_id"] == str(self.github_ticket.id)
        assert call_kwargs["content"] == "We are looking into this"

    @parameterized.expand(
        [
            # (name, created_by_is_user, item_context)
            ("private_message", True, {"author_type": "support", "is_private": True}),
            ("customer_message", False, {"author_type": "customer", "is_private": False}),
            ("from_github_echo", False, {"author_type": "customer", "is_private": False, "from_github": True}),
        ]
    )
    @patch("products.conversations.backend.tasks.post_reply_to_github.delay")
    def test_does_not_enqueue(self, _name, created_by_is_user, item_context, mock_delay, _mock_on_commit):
        Comment.objects.create(
            team=self.team,
            scope="conversations_ticket",
            item_id=str(self.github_ticket.id),
            content="Some message",
            created_by=self.user if created_by_is_user else None,
            item_context=item_context,
        )

        mock_delay.assert_not_called()

    @patch("products.conversations.backend.tasks.post_reply_to_github.delay")
    def test_github_disabled_does_not_enqueue(self, mock_delay, _mock_on_commit):
        self.team.conversations_settings["github_enabled"] = False
        self.team.save()

        Comment.objects.create(
            team=self.team,
            scope="conversations_ticket",
            item_id=str(self.github_ticket.id),
            content="Reply",
            created_by=self.user,
            item_context={"author_type": "support", "is_private": False},
        )

        mock_delay.assert_not_called()

    @patch("products.conversations.backend.tasks.post_reply_to_github.delay")
    def test_non_github_ticket_does_not_enqueue(self, mock_delay, _mock_on_commit):
        slack_ticket = Ticket.objects.create_with_number(
            team=self.team,
            widget_session_id="",
            distinct_id="slack-user",
            channel_source=Channel.SLACK,
            slack_channel_id="C123",
            slack_thread_ts="123.456",
        )
        Comment.objects.create(
            team=self.team,
            scope="conversations_ticket",
            item_id=str(slack_ticket.id),
            content="Reply on slack ticket",
            created_by=self.user,
            item_context={"author_type": "support", "is_private": False},
        )

        mock_delay.assert_not_called()
