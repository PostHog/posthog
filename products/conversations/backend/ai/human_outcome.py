"""Record whether a human public reply used, edited, or ignored the AI draft.

A metric on `ai_triage.human_outcome`, not a learning input.
"""

from __future__ import annotations

import re
from typing import Literal

from django.db import models, transaction
from django.db.models import Q, QuerySet

from rapidfuzz.distance import Indel

from posthog.models.comment import Comment

from products.conversations.backend.models import Ticket

HumanOutcome = Literal["used", "edited", "ignored"]


class AiDraftHumanOutcome(models.TextChoices):
    USED = "used", "used"
    EDITED = "edited", "edited"


# Near-copy of the draft counts as used; some overlap as edited; the rest as ignored.
USED_RATIO = 0.85
EDITED_RATIO = 0.4


# Chinese, Japanese, Thai and Korean write without spaces between words, so a run of word
# characters is a whole sentence. One token per character there keeps a small edit from
# replacing the only token the sentence has.
_UNSPACED_SCRIPTS = "぀-ヿ㐀-䶿一-鿿豈-﫿가-힯฀-๿"
_TOKEN_PATTERN = re.compile(rf"[{_UNSPACED_SCRIPTS}]|[^\W{_UNSPACED_SCRIPTS}]+")


def classify_human_outcome(ai_draft: str, human_reply: str) -> HumanOutcome:
    draft = ai_draft.strip()
    reply = human_reply.strip()
    if not draft or not reply:
        return "ignored"
    if draft == reply:
        return "used"
    draft_tokens = _TOKEN_PATTERN.findall(draft.lower())
    reply_tokens = _TOKEN_PATTERN.findall(reply.lower())
    if not draft_tokens or not reply_tokens:
        return "ignored"
    total_tokens = len(draft_tokens) + len(reply_tokens)
    # Length alone caps how similar two texts can be. Settling that case without matching keeps
    # the ticket row lock short on the common path, where the human wrote their own reply.
    if 2 * min(len(draft_tokens), len(reply_tokens)) / total_tokens < EDITED_RATIO:
        return "ignored"
    # rapidfuzz matches both whole token lists in bit-parallel C, fast enough to run under the ticket
    # row lock without a cap, so text kept anywhere in a long draft counts. Matching characters instead
    # would score unrelated replies as edited, because two texts in one language share many letters in order.
    ratio = Indel.normalized_similarity(draft_tokens, reply_tokens)
    if ratio >= USED_RATIO:
        return "used"
    if ratio >= EDITED_RATIO:
        return "edited"
    return "ignored"


def _inserted_draft_text(ai_note: Comment) -> str:
    context = ai_note.item_context or {}
    if context.get("persist_as") not in {"clarification", "findings"}:
        return ai_note.content or ""
    questions = context.get("clarifying_questions")
    if not isinstance(questions, list):
        return ai_note.content or ""
    return next((question.strip() for question in questions if isinstance(question, str) and question.strip()), "")


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


def record_human_outcome(*, team_id: int, ticket_id: str, draft_message_id: str, outcome: HumanOutcome) -> bool:
    """Write `human_outcome` if unset, or upgrade `used` to `edited` after a composer edit."""
    with transaction.atomic():
        ticket = Ticket.objects.select_for_update().filter(id=ticket_id, team_id=team_id).first()
        if ticket is None:
            return False
        latest_ai_draft_id = (
            _ticket_comments(team_id=team_id, ticket_id=ticket_id)
            .filter(item_context__author_type="AI", item_context__is_private=True, deleted=False)
            .filter(item_context__automated_update_key__isnull=True)
            .order_by("-created_at", "-id")
            .values_list("id", flat=True)
            .first()
        )
        if latest_ai_draft_id is None or str(latest_ai_draft_id) != draft_message_id:
            return False
        triage = dict(ticket.ai_triage or {})
        current = triage.get("human_outcome")
        if current == outcome:
            return True
        if current and not (current == "used" and outcome == "edited"):
            return False
        triage["human_outcome"] = outcome
        ticket.ai_triage = triage
        ticket.save(update_fields=["ai_triage", "updated_at"])
        return True


def maybe_record_human_outcome(*, team_id: int, ticket_id: str, comment_id: str, human_content: str) -> None:
    """Set `ai_triage.human_outcome` on the first public human reply after the latest AI note."""
    if not human_content.strip():
        return

    with transaction.atomic():
        ticket = Ticket.objects.select_for_update().filter(id=ticket_id, team_id=team_id).first()
        if ticket is None:
            return
        triage = dict(ticket.ai_triage or {})
        current = triage.get("human_outcome")

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
            comments.filter(item_context__author_type="AI", item_context__is_private=True, deleted=False)
            .filter(item_context__automated_update_key__isnull=True)
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

        draft_text = _inserted_draft_text(ai_note)
        if not draft_text.strip():
            # Investigation notes with no suggested question give the human nothing to adopt.
            return
        classified = classify_human_outcome(draft_text, human_content)
        if current == classified:
            return
        if current and current != "used":
            return

        triage["human_outcome"] = classified
        ticket.ai_triage = triage
        ticket.save(update_fields=["ai_triage", "updated_at"])
