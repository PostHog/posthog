"""Handlers for buttons that a product posts in the PostHog Slack app's messages.

Slack sends every click on the PostHog Slack app to one interactivity URL, which the slack_app
product serves. A product that posts its own messages registers a handler for the action ids it
puts on its buttons, so slack_app can dispatch the click without importing that product.

The value of a registered button is a JSON object whose ``integration_id`` is the id of the
integration that posted the message. slack_app reads it to find the region that owns the click
and forwards the click there. The handler then runs in that region.

Keep this module light: products register from ``AppConfig.ready()``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

# (payload, action) -> None. The action is the entry of ``payload["actions"]`` that matched.
# Slack expects an answer within 3 seconds, so a handler does its writes and queues the rest.
BlockActionHandler = Callable[[dict[str, Any], dict[str, Any]], None]

_handlers: dict[str, BlockActionHandler] = {}


def register_block_action_handler(prefix: str, handler: BlockActionHandler) -> None:
    """Send every block action whose action id starts with ``prefix`` to ``handler``.

    A prefix may not overlap another product's prefix, because a click must have exactly one owner.
    """
    if not prefix:
        raise ValueError("A block action prefix must not be empty")
    for registered in _handlers:
        if registered != prefix and (registered.startswith(prefix) or prefix.startswith(registered)):
            raise ValueError(f"Block action prefix {prefix!r} overlaps {registered!r}")
    _handlers[prefix] = handler


def block_action_handler_for(action_id: str) -> BlockActionHandler | None:
    for prefix, handler in _handlers.items():
        if action_id.startswith(prefix):
            return handler
    return None
