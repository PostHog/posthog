from collections.abc import Sequence
from typing import Any

from anthropic.types import Message

# Enough of the body to recognize a proxy error page or plain-text response, without dumping it all.
UNEXPECTED_BODY_EXCERPT_CHARS = 500


class UnexpectedGatewayResponseError(Exception):
    """The gateway returned a body the Anthropic SDK could not parse into a ``Message``.

    Our gateway clients run with the SDK's default (non-strict) response validation, which hands
    back the raw body as a ``str`` whenever the response isn't JSON — a proxy error page, a
    plain-text 200. Reading ``.content`` on that fails with an unrelated ``AttributeError``, so
    guard the boundary with :func:`anthropic_text_blocks` and get this instead. Transient by
    nature, so it's safe to retry.
    """


def _body_excerpt(response: Any) -> str:
    body = response if isinstance(response, str) else repr(response)
    if len(body) > UNEXPECTED_BODY_EXCERPT_CHARS:
        return f"{body[:UNEXPECTED_BODY_EXCERPT_CHARS]}… (truncated)"
    return body


def _ensure_message(response: Any) -> Message:
    # Duck-typed rather than isinstance(response, Message) so wrapped or stubbed responses still
    # pass; what we're rejecting is a raw body that never went through parsing.
    content = getattr(response, "content", None)
    if isinstance(content, Sequence) and not isinstance(content, str | bytes):
        return response
    raise UnexpectedGatewayResponseError(
        f"Expected an Anthropic Message, got {type(response).__name__}: {_body_excerpt(response)}"
    )


def anthropic_text_blocks(response: Any) -> list[str]:
    """Text of each text block of a Messages response, in order, ignoring non-text blocks.

    Raises :class:`UnexpectedGatewayResponseError` when the response isn't a parsed ``Message``.
    """
    message = _ensure_message(response)
    return [getattr(block, "text", "") for block in message.content if getattr(block, "type", None) == "text"]
