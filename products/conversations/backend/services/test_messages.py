from django.test import SimpleTestCase

from parameterized import parameterized

from products.conversations.backend.models.constants import TicketMessageType
from products.conversations.backend.services.messages import ticket_message_type


class TestTicketMessageType(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "published_ai_reply",
                {"author_type": "AI", "is_private": False, "persist_as": "reply"},
                None,
                TicketMessageType.SENT_REPLY,
            ),
            (
                "imported_team_reply",
                {"author_type": "support", "is_private": False},
                None,
                TicketMessageType.SENT_REPLY,
            ),
            (
                "ai_draft_reply",
                {"author_type": "AI", "is_private": True, "persist_as": "reply"},
                None,
                TicketMessageType.AI_DRAFT,
            ),
            (
                "ai_suggested_question",
                {"author_type": "AI", "is_private": True, "persist_as": "clarification"},
                None,
                TicketMessageType.AI_DRAFT,
            ),
            (
                "ai_draft_without_persist_as",
                {"author_type": "AI", "is_private": True},
                None,
                TicketMessageType.AI_DRAFT,
            ),
            (
                "ai_findings",
                {"author_type": "AI", "is_private": True, "persist_as": "findings"},
                None,
                TicketMessageType.INTERNAL_NOTE,
            ),
            (
                "automation_note",
                {"author_type": "AI", "is_private": True, "internal_note_key": "signals_report:example"},
                None,
                TicketMessageType.INTERNAL_NOTE,
            ),
            (
                "teammate_note_labeled_ai",
                {"author_type": "AI", "is_private": True},
                1,
                TicketMessageType.INTERNAL_NOTE,
            ),
        ]
    )
    def test_ticket_message_type(
        self, _name: str, item_context: dict, created_by_id: int | None, expected: TicketMessageType
    ) -> None:
        assert ticket_message_type(item_context, created_by_id) == expected
