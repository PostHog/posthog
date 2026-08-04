import uuid

from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.models.comment import Comment

from products.conversations.backend.models import Ticket
from products.conversations.backend.models.constants import Channel
from products.conversations.backend.tasks import process_ticket_message_side_effects

TASKS = "products.conversations.backend.tasks"


@patch(f"{TASKS}.ph_scoped_capture")
@patch(f"{TASKS}.capture_message_received")
@patch(f"{TASKS}.capture_message_sent")
class TestProcessTicketMessageSideEffects(BaseTest):
    def setUp(self):
        super().setUp()
        self.ticket = Ticket.objects.create_with_number(
            team=self.team,
            widget_session_id=str(uuid.uuid4()),
            distinct_id="user-123",
            channel_source=Channel.WIDGET,
        )

    def _message(self, *, author_type: str, is_private: bool = False, with_author: bool = False) -> Comment:
        return Comment.objects.create(
            team=self.team,
            scope="conversations_ticket",
            item_id=str(self.ticket.id),
            content="Hello",
            created_by=self.user if with_author else None,
            item_context={"author_type": author_type, "is_private": is_private},
        )

    def _run(self, comment: Comment) -> None:
        process_ticket_message_side_effects(team_id=self.team.id, comment_id=str(comment.id))

    @parameterized.expand(
        [
            ("customer", "customer", False, False, False, True),
            ("team_human", "team", False, True, True, False),
            ("public_ai", "AI", False, False, True, False),
            ("private_note", "team", True, True, False, False),
        ]
    )
    def test_emits_the_customer_facing_event_for_the_right_author(
        self,
        mock_sent,
        mock_received,
        mock_scoped_capture,
        _name,
        author_type,
        is_private,
        with_author,
        expect_sent,
        expect_received,
    ):
        comment = self._message(author_type=author_type, is_private=is_private, with_author=with_author)

        self._run(comment)

        assert mock_sent.called is expect_sent
        assert mock_received.called is expect_received

    def test_attributes_a_team_reply_to_its_author(self, mock_sent, mock_received, mock_scoped_capture):
        comment = self._message(author_type="team", with_author=True)

        self._run(comment)

        assert mock_sent.call_args.kwargs["author"] == self.user
        capture = mock_scoped_capture.return_value.__enter__.return_value
        assert capture.call_args.kwargs["distinct_id"] == self.user.distinct_id
        assert capture.call_args.kwargs["event"] == "support message sent"

    def test_attributes_a_customer_message_to_the_team(self, mock_sent, mock_received, mock_scoped_capture):
        comment = self._message(author_type="customer")

        self._run(comment)

        capture = mock_scoped_capture.return_value.__enter__.return_value
        assert capture.call_args.kwargs["distinct_id"] == str(self.team.uuid)
        assert capture.call_args.kwargs["event"] == "support message received"
        assert capture.call_args.kwargs["properties"]["channel_source"] == Channel.WIDGET

    @parameterized.expand(
        [
            ("missing_comment", "missing"),
            ("deleted_comment", "deleted"),
            ("missing_ticket", "orphan"),
        ]
    )
    def test_is_a_no_op_when_there_is_nothing_to_report(
        self, mock_sent, mock_received, mock_scoped_capture, _name, case
    ):
        if case == "missing":
            process_ticket_message_side_effects(team_id=self.team.id, comment_id=str(uuid.uuid4()))
        elif case == "deleted":
            comment = self._message(author_type="customer")
            Comment.objects.filter(id=comment.id).update(deleted=True)
            self._run(comment)
        else:
            comment = self._message(author_type="customer")
            Comment.objects.filter(id=comment.id).update(item_id=str(uuid.uuid4()))
            self._run(comment)

        assert not mock_sent.called
        assert not mock_received.called

    @patch("posthog.tasks.email.send_new_ticket_notification.delay")
    def test_notifies_recipients_about_the_message_that_opened_the_ticket(
        self, mock_notify, mock_sent, mock_received, mock_scoped_capture
    ):
        self.team.conversations_settings = {"notification_recipients": ["support@posthog.com"]}
        self.team.save()

        self._run(self._message(author_type="customer"))

        mock_notify.assert_called_once_with(
            ticket_id=str(self.ticket.id), team_id=self.team.id, first_message_content="Hello"
        )

    @patch("posthog.tasks.email.send_new_ticket_notification.delay")
    def test_does_not_notify_about_a_later_customer_message(
        self, mock_notify, mock_sent, mock_received, mock_scoped_capture
    ):
        self.team.conversations_settings = {"notification_recipients": ["support@posthog.com"]}
        self.team.save()
        self._message(author_type="customer")

        self._run(self._message(author_type="customer"))

        mock_notify.assert_not_called()

    @patch("posthog.tasks.email.send_new_ticket_notification.delay")
    def test_notifies_even_when_the_denormalized_message_count_has_drifted(
        self, mock_notify, mock_sent, mock_received, mock_scoped_capture
    ):
        # A request that died mid-flight can leave message_count behind the real message
        # count; the notification is gated on the messages themselves, not that counter.
        self.team.conversations_settings = {"notification_recipients": ["support@posthog.com"]}
        self.team.save()
        comment = self._message(author_type="customer")
        Ticket.objects.filter(id=self.ticket.id).update(message_count=0)

        self._run(comment)

        mock_notify.assert_called_once()

    @patch("posthog.tasks.email.send_new_ticket_notification.delay")
    def test_does_not_notify_when_no_recipients_are_configured(
        self, mock_notify, mock_sent, mock_received, mock_scoped_capture
    ):
        self._run(self._message(author_type="customer"))

        mock_notify.assert_not_called()
