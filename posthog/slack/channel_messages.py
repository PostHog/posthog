"""Handlers for top-level messages that people post in a channel the PostHog Slack app is in.

Slack sends every channel message to the slack_app product. A product that acts on some of these
messages registers a handler here, so slack_app can call it without importing that product.

slack_app calls the handlers only for a top-level post by a person: not a thread reply, a bot, an
edit or another subtype, and not a message in an externally shared channel. It calls them in every
region that holds a Slack connection for the workspace, so a handler acts only for the projects in
its own region.

Keep this module light: products register from ``AppConfig.ready()``.
"""

from __future__ import annotations

from collections.abc import Callable

import structlog

from posthog.dataclasses import frozen

logger = structlog.get_logger(__name__)


@frozen
class ChannelMessage:
    slack_team_id: str
    channel_id: str
    message_ts: str
    slack_user_id: str
    text: str
    # The PostHog accounts of the person who posted, the account the Slack app resolves for them first,
    # or an empty tuple. The lookup can call Slack, so a handler calls it only after its own cheap checks.
    poster_user_ids: Callable[[], tuple[int, ...]]


# Returns True when the handler takes the message, so slack_app does not also answer it. The handler runs
# inside Slack's 3-second request for every top-level post, so it rejects other messages without a query and
# queues its work.
ChannelMessageHandler = Callable[[ChannelMessage], bool]

_handlers: dict[str, ChannelMessageHandler] = {}


def register_channel_message_handler(name: str, handler: ChannelMessageHandler) -> None:
    _handlers[name] = handler


def dispatch_channel_message(message: ChannelMessage) -> bool:
    """Offer the message to every handler, and return whether one of them took it. Never raises."""
    handled = False
    for name, handler in _handlers.items():
        try:
            handled = handler(message) or handled
        except Exception:
            logger.exception("slack_channel_message_handler_failed", handler=name)
    return handled
