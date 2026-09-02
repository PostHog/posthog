from django.test import SimpleTestCase

from parameterized import parameterized

from products.conversations.backend.ai.suggest import _format_enhanced_context


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
