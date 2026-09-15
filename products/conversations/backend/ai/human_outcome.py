"""Record whether a human public reply used, edited, or ignored the AI draft.

A metric on `ai_triage.human_outcome`, not a learning input.
"""

from __future__ import annotations

from difflib import SequenceMatcher
from typing import Literal

from django.db import transaction
from django.db.models import Q, QuerySet

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


def _ticket_comments(*, team_id: int, ticket_id: str) -> QuerySet[Comment]:
    return Comment.objects.filter(
        team_id=team_id,
        scope="conversations_ticket",
        item_id=str(ticket_id),
    )


def _public_human_comments(comments: QuerySet[Comment]) -> QuerySet[Comment]:
    return (
        comments.filter(created_by_id__isnull=False)
        .exclude(item_context__author_type="customer")
        .exclude(item_context__is_private=True)
    )


def maybe_record_human_outcome(*, team_id: int, ticket_id: str, comment_id: str, human_content: str) -> None:
    """Set `ai_triage.human_outcome` on the first public human reply after the latest AI note."""
    if not human_content.strip():
        return

    with transaction.atomic():
        ticket = Ticket.objects.select_for_update().filter(id=ticket_id, team_id=team_id).first()
        if ticket is None:
            return
        triage = dict(ticket.ai_triage or {})
        if triage.get("human_outcome"):
            return

        comments = _ticket_comments(team_id=team_id, ticket_id=ticket_id)
        this_comment = comments.filter(id=comment_id).first()
        if this_comment is None:
            return

        before_this = Q(created_at__lt=this_comment.created_at) | Q(
            created_at=this_comment.created_at, id__lt=this_comment.id
        )
        # Only private AI notes are drafts a human can adopt. A public AI reply was auto-sent
        # to the customer, so a later human reply is a follow-up, not adoption of a draft.
        ai_note = (
            comments.filter(item_context__author_type="AI", item_context__is_private=True)
            .filter(before_this)
            .order_by("-created_at", "-id")
            .first()
        )
        if ai_note is None or not (ai_note.content or "").strip():
            return

        after_ai = Q(created_at__gt=ai_note.created_at) | Q(created_at=ai_note.created_at, id__gt=ai_note.id)
        first_after = _public_human_comments(comments).filter(after_ai).order_by("created_at", "id").first()
        if first_after is None or str(first_after.id) != str(comment_id):
            return

        triage["human_outcome"] = classify_human_outcome(ai_note.content or "", human_content)
        ticket.ai_triage = triage
        ticket.save(update_fields=["ai_triage", "updated_at"])
