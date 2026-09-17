from unittest.mock import MagicMock

from django.test import SimpleTestCase

from parameterized import parameterized

from products.conversations.backend.ai.suggest import _format_enhanced_context, format_conversation


class TestFormatEnhancedContext(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "canonical array properties",
                {"properties.$exception_types": ["TypeError"], "properties.$exception_values": ["Bad call"]},
            ),
            (
                "legacy scalar properties",
                {"properties.$exception_type": "TypeError", "properties.$exception_message": "Bad call"},
            ),
        ]
    )
    def test_formats_exception_type_and_message(self, _name: str, exception: dict[str, object]) -> None:
        context = _format_enhanced_context("Conversation", [], [exception])

        assert "TypeError: Bad call" in context


class TestFormatConversation(SimpleTestCase):
    @parameterized.expand(
        [
            ("customer", {"author_type": "customer", "is_private": False}, "[Customer]: hi"),
            ("human_public", {"author_type": "team", "is_private": False}, "[Support]: hi"),
            ("human_private", {"author_type": "team", "is_private": True}, "[Support (private note)]: hi"),
            ("ai_public", {"author_type": "AI", "is_private": False}, "[AI assistant]: hi"),
            ("ai_private", {"author_type": "AI", "is_private": True}, "[AI (private note)]: hi"),
        ]
    )
    def test_author_labels(self, _name: str, item_context: dict[str, object], expected: str) -> None:
        ticket = MagicMock()
        ticket.session_context = None
        message = MagicMock()
        message.item_context = item_context
        message.content = "hi"
        assert expected in format_conversation(ticket, [message])
