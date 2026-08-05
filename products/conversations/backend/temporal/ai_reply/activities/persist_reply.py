from __future__ import annotations

from temporalio import activity

from posthog.models.comment import Comment
from posthog.sync import database_sync_to_async
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.utils import close_db_connections

from products.conversations.backend.models import Ticket
from products.conversations.backend.temporal.ai_reply.constants import PUBLISHABLE_TICKET_TYPES
from products.conversations.backend.temporal.ai_reply.schemas import PersistReplyInput


@activity.defn
@close_db_connections
async def support_persist_reply_activity(input: PersistReplyInput) -> None:
    """Persist the validated reply as an AI comment on the ticket (private note or bot reply per settings)."""
    async with Heartbeater():
        await database_sync_to_async(_persist_reply_sync, thread_sensitive=False)(
            input.team_id,
            input.ticket_id,
            input.reply,
            input.citations,
            input.confidence,
            input.ticket_type,
            input.allow_bot_reply,
        )


def _persist_reply_sync(
    team_id: int,
    ticket_id: str,
    reply: str,
    citations: list[str],
    confidence: float,
    ticket_type: str = "how_to",
    allow_bot_reply: bool = False,
) -> None:
    is_private = True
    # Only how_to replies may be published. diagnostic/account_billing draw on project data and
    # must stay private regardless of the team's ai_reply_modes — guards against stale settings
    # since validation now rejects bot_reply for those types. Controlled by team-level opt-in.
    if allow_bot_reply and ticket_type in PUBLISHABLE_TICKET_TYPES:
        ticket = Ticket.objects.select_related("team").filter(team_id=team_id, id=ticket_id).first()
        if ticket:
            settings_dict = ticket.team.conversations_settings or {}
            modes = settings_dict.get("ai_reply_modes") or {}
            channel_modes = modes.get(ticket.channel_source) or {}
            mode = channel_modes.get(ticket_type, "private_note")
            if mode == "bot_reply":
                is_private = False

    Comment.objects.create(
        team_id=team_id,
        scope="conversations_ticket",
        item_id=ticket_id,
        content=reply,
        item_context={
            "author_type": "AI",
            "is_private": is_private,
            "citations": citations,
            "confidence": confidence,
        },
    )
