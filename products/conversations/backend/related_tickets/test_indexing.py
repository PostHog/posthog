from posthog.test.base import BaseTest
from unittest.mock import patch

from posthog.models.comment import Comment

from products.conversations.backend.models import Ticket
from products.conversations.backend.models.constants import Channel, Status
from products.conversations.backend.related_tickets.indexing import embed_conversations_ticket


class TestEmbedConversationsTicket(BaseTest):
    def _make_ticket(self) -> Ticket:
        ticket = Ticket.objects.create_with_number(
            team=self.team,
            widget_session_id="session-123",
            distinct_id="user-1",
            channel_source=Channel.WIDGET,
            email_subject="Billing question",
            status=Status.OPEN,
        )
        Comment.objects.create(
            team=self.team,
            scope="conversations_ticket",
            item_id=str(ticket.id),
            content="Why was I charged twice?",
            item_context={"author_type": "customer", "is_private": False},
        )
        return ticket

    def _approve_consent(self, approved: bool) -> None:
        self.organization.is_ai_data_processing_approved = approved
        self.organization.save()

    @patch("products.conversations.backend.related_tickets.indexing.emit_embedding_request")
    def test_emits_with_expected_arguments_when_consent_approved(self, mock_emit):
        self._approve_consent(True)
        ticket = self._make_ticket()

        embed_conversations_ticket(self.team.id, str(ticket.id))

        mock_emit.assert_called_once()
        args, kwargs = mock_emit.call_args
        assert args[0].startswith("Billing question")
        assert kwargs["team_id"] == self.team.id
        assert kwargs["product"] == "conversations"
        assert kwargs["document_type"] == "ticket"
        assert kwargs["rendering"] == "ticket_plain"
        assert kwargs["document_id"] == str(ticket.id)
        assert kwargs["models"] == ["text-embedding-3-small-1536"]
        assert kwargs["timestamp"] is not None and kwargs["timestamp"].tzinfo is not None
        assert kwargs["metadata"]["ticket_id"] == str(ticket.id)

    @patch("products.conversations.backend.related_tickets.indexing.emit_embedding_request")
    def test_does_not_emit_when_consent_not_approved(self, mock_emit):
        self._approve_consent(False)
        ticket = self._make_ticket()

        embed_conversations_ticket(self.team.id, str(ticket.id))

        mock_emit.assert_not_called()

    @patch("products.conversations.backend.related_tickets.indexing.emit_embedding_request")
    def test_does_not_emit_for_empty_ticket(self, mock_emit):
        self._approve_consent(True)
        ticket = Ticket.objects.create_with_number(
            team=self.team,
            widget_session_id="session-123",
            distinct_id="user-1",
            channel_source=Channel.WIDGET,
        )

        embed_conversations_ticket(self.team.id, str(ticket.id))

        mock_emit.assert_not_called()
