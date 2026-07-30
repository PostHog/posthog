import pytest
from unittest.mock import MagicMock

from posthog.llm.anthropic_response import (
    UNEXPECTED_BODY_EXCERPT_CHARS,
    UnexpectedGatewayResponseError,
    anthropic_text_blocks,
)


@pytest.mark.parametrize(
    "response",
    [
        "<html><body>502 Bad Gateway</body></html>",
        "upstream request timeout",
        b"raw bytes body",
        object(),
    ],
)
def test_rejects_bodies_without_content_blocks(response):
    with pytest.raises(UnexpectedGatewayResponseError):
        anthropic_text_blocks(response)


def test_error_names_the_unexpected_body_truncated():
    body = "x" * (UNEXPECTED_BODY_EXCERPT_CHARS + 100)

    with pytest.raises(UnexpectedGatewayResponseError) as exc_info:
        anthropic_text_blocks(body)

    message = str(exc_info.value)
    assert "str" in message
    assert "truncated" in message
    assert len(message) < UNEXPECTED_BODY_EXCERPT_CHARS + 200


def test_returns_text_blocks_in_order_ignoring_other_blocks():
    text_a, thinking, text_b = (
        MagicMock(type="text", text="a"),
        MagicMock(type="thinking"),
        MagicMock(type="text", text="b"),
    )
    response = MagicMock(content=[text_a, thinking, text_b])

    assert anthropic_text_blocks(response) == ["a", "b"]
