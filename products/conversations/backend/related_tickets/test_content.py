from posthog.test.base import BaseTest

from posthog.models.comment import Comment
from posthog.temporal.data_imports.signals.conversations_tickets import MAX_DESCRIPTION_CHARS

from products.conversations.backend.models import Ticket
from products.conversations.backend.models.constants import Channel, Status
from products.conversations.backend.related_tickets.content import compose_ticket_text


class TestComposeTicketText(BaseTest):
    def _make_ticket(self, **kwargs) -> Ticket:
        defaults = {
            "team": self.team,
            "widget_session_id": "session-123",
            "distinct_id": "user-1",
            "channel_source": Channel.WIDGET,
        }
        defaults.update(kwargs)
        return Ticket.objects.create_with_number(**defaults)

    def _add_message(self, ticket: Ticket, content: str, author_type: str, is_private: bool = False) -> Comment:
        return Comment.objects.create(
            team=self.team,
            scope="conversations_ticket",
            item_id=str(ticket.id),
            content=content,
            created_by=self.user if author_type != "customer" else None,
            item_context={"author_type": author_type, "is_private": is_private},
        )

    def test_returns_none_for_missing_ticket(self):
        assert compose_ticket_text(self.team.id, "00000000-0000-0000-0000-000000000000") is None

    def test_returns_none_when_no_content(self):
        ticket = self._make_ticket()
        assert compose_ticket_text(self.team.id, str(ticket.id)) is None

    def test_builds_subject_and_tagged_thread(self):
        ticket = self._make_ticket(email_subject="Login is broken", status=Status.OPEN)
        self._add_message(ticket, "I cannot log in", author_type="customer")
        self._add_message(ticket, "Have you tried resetting?", author_type="support")

        result = compose_ticket_text(self.team.id, str(ticket.id))
        assert result is not None
        content, metadata, last_activity = result

        assert content == "Login is broken\nC: I cannot log in\nT: Have you tried resetting?"
        assert metadata["source"] == "conversations"
        assert metadata["title"] == "Login is broken"
        assert metadata["status"] == Status.OPEN
        assert metadata["ticket_number"] == ticket.ticket_number
        assert metadata["ticket_id"] == str(ticket.id)
        assert metadata["last_activity"] is not None
        assert last_activity is not None and last_activity.tzinfo is not None

    def test_excludes_private_notes(self):
        ticket = self._make_ticket()
        self._add_message(ticket, "Public question", author_type="customer")
        self._add_message(ticket, "Internal note do not show", author_type="support", is_private=True)

        result = compose_ticket_text(self.team.id, str(ticket.id))
        assert result is not None
        content, _, _ = result
        assert "Internal note do not show" not in content
        assert content == "C: Public question"

    def test_respects_truncation_budget(self):
        ticket = self._make_ticket()
        huge = "x" * (MAX_DESCRIPTION_CHARS + 5000)
        self._add_message(ticket, huge, author_type="customer")
        self._add_message(ticket, "later reply", author_type="support")

        result = compose_ticket_text(self.team.id, str(ticket.id))
        assert result is not None
        content, _, _ = result
        assert len(content) <= MAX_DESCRIPTION_CHARS
        assert "later reply" not in content

    def test_falls_back_to_last_message_text_when_no_messages(self):
        ticket = self._make_ticket(last_message_text="A preview line")

        result = compose_ticket_text(self.team.id, str(ticket.id))
        assert result is not None
        content, metadata, _ = result
        assert content == "A preview line"
        assert metadata["title"] == f"Ticket #{ticket.ticket_number}"

    def test_title_falls_back_to_customer_message_preview(self):
        ticket = self._make_ticket()
        self._add_message(ticket, "T: agent greeting", author_type="support")
        self._add_message(ticket, "My actual problem", author_type="customer")

        result = compose_ticket_text(self.team.id, str(ticket.id))
        assert result is not None
        _, metadata, _ = result
        assert metadata["title"] == "My actual problem"
