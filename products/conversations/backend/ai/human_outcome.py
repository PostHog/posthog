"""Record whether a human public reply used, edited, or ignored the AI draft.

A metric on `ai_triage.human_outcome`, not a learning input.
"""

from __future__ import annotations

from difflib import SequenceMatcher
from typing import Literal

from django.db import transaction

from posthog.models.comment import Comment

from products.conversations.backend.models import Ticket

HumanOutcome = Literal["used", "edited", "ignored"]

# Near-copy of the draft counts as used; some overlap as edited; the rest as ignored.
USED_RATIO = 0.85
EDITED_RATIO = 0.4


def classify_human_outcome(ai_draft: str, human_reply: str) -> HumanOutcome:
    ratio = SequenceMatcher(None, ai_draft.strip(), human_reply.strip()).ratio()
    if ratio >= USED_RATIO:
        return "used"
    if ratio >= EDITED_RATIO:
        return "edited"
    return "ignored"


def maybe_record_human_outcome(*, team_id: int, ticket_id: str, human_content: str) -> None:
    """Set `ai_triage.human_outcome` on the first public human reply after an AI note."""
    if not human_content.strip():
        return

    with transaction.atomic():
        ticket = Ticket.objects.select_for_update().filter(id=ticket_id, team_id=team_id).first()
        if ticket is None:
            return
        triage = dict(ticket.ai_triage or {})
        if triage.get("human_outcome"):
            return

        comments = Comment.objects.filter(
            team_id=team_id,
            scope="conversations_ticket",
            item_id=str(ticket_id),
        )
        human_public = (
            comments.filter(created_by_id__isnull=False)
            .exclude(item_context__author_type="customer")
            .exclude(item_context__is_private=True)
        )
        if human_public.count() != 1:
            return

        ai_note = comments.filter(item_context__author_type="AI").order_by("-created_at").first()
        if ai_note is None or not (ai_note.content or "").strip():
            return

        triage["human_outcome"] = classify_human_outcome(ai_note.content or "", human_content)
        ticket.ai_triage = triage
        ticket.save(update_fields=["ai_triage", "updated_at"])
