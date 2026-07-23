from email import message_from_bytes

from posthog.test.base import BaseTest
from unittest.mock import patch

from posthog.models.comment import Comment

from products.conversations.backend.models import EmailChannel, EmailOutboxMessage, Ticket
from products.conversations.backend.models.constants import Channel, Status
from products.conversations.backend.tasks import _process_outbox_row


class TestEmailReplyRecipients(BaseTest):
    def setUp(self):
        super().setUp()
        self.team.conversations_settings = {"email_enabled": True}
        self.team.save()
        self.config = EmailChannel.objects.create(
            team=self.team,
            inbound_token="ccbcctest0001",
            from_email="support@example.com",
            from_name="Support",
            domain="example.com",
            domain_verified=True,
        )
        self.ticket = Ticket.objects.create_with_number(
            team=self.team,
            channel_source=Channel.EMAIL,
            email_config=self.config,
            widget_session_id="",
            distinct_id="customer@external.com",
            email_from="customer@external.com",
            email_subject="Help",
            status=Status.OPEN,
            cc_participants=["persisted@example.com"],
        )

    def _send(self, item_context: dict) -> tuple[list[str], object]:
        comment = Comment.objects.create(
            team=self.team,
            created_by=self.user,
            scope="conversations_ticket",
            item_id=str(self.ticket.id),
            content="reply body",
            item_context=item_context,
        )
        outbox = EmailOutboxMessage.objects.create(
            team=self.team,
            ticket=self.ticket,
            comment=comment,
            message_id="<msg-1@example.com>",
        )
        with patch("products.conversations.backend.tasks.send_mime") as mock_send:
            _process_outbox_row(outbox)
        recipients = mock_send.call_args.kwargs["recipients"]
        parsed = message_from_bytes(mock_send.call_args.args[1])
        return recipients, parsed

    def test_bcc_reaches_envelope_but_not_headers(self) -> None:
        recipients, parsed = self._send({"author_type": "support", "is_private": False, "bcc": ["secret@example.com"]})
        # Blind copies must be delivered (envelope) but never disclosed in the message headers.
        assert "secret@example.com" in recipients
        assert parsed["Bcc"] is None
        assert "secret@example.com" not in (parsed.as_string())

    def test_cc_unions_persisted_and_per_message(self) -> None:
        recipients, parsed = self._send({"author_type": "support", "is_private": False, "cc": ["extra@example.com"]})
        assert "persisted@example.com" in recipients
        assert "extra@example.com" in recipients
        # Cc, unlike Bcc, is a visible header.
        assert "persisted@example.com" in parsed["Cc"]
        assert "extra@example.com" in parsed["Cc"]

    def test_primary_recipient_never_duplicated_in_cc(self) -> None:
        recipients, parsed = self._send(
            {"author_type": "support", "is_private": False, "cc": ["customer@external.com"]}
        )
        assert recipients.count("customer@external.com") == 1
        assert parsed["Cc"] is None or "customer@external.com" not in parsed["Cc"]
