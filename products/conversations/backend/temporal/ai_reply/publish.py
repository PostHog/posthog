from __future__ import annotations

from typing import TYPE_CHECKING

from products.conversations.backend.temporal.ai_reply.constants import PUBLISHABLE_TICKET_TYPES

if TYPE_CHECKING:
    from products.conversations.backend.models import Ticket


def channel_allows_bot_reply(*, ticket: Ticket, ticket_type: str) -> bool:
    """True when this ticket's channel is set to auto-send this publishable type.

    Mirrors persist_reply's publish gate so clarifying questions and replies cannot drift.
    """
    if ticket_type not in PUBLISHABLE_TICKET_TYPES:
        return False
    # The AI reads a forwarded ticket's forwarded email, which can carry internal mail, so a person sends replies.
    if (ticket.anonymous_traits or {}).get("email_forwarded") is True:
        return False
    settings_dict = ticket.team.conversations_settings or {}
    modes = settings_dict.get("ai_reply_modes") or {}
    channel_modes = modes.get(ticket.channel_source) or {}
    return channel_modes.get(ticket_type, "private_note") == "bot_reply"
