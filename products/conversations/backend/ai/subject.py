"""AI-generated ticket subjects.

A ticket's subject is a short, accurate summary of what the thread is about. It's
generated (and kept fresh) by a cheap utility LLM whenever a public reply lands,
gated behind a per-team opt-in, a feature flag, and the org's AI data-processing
consent. Only tickets without a human/channel-provided subject (``email_subject``)
are managed here — that field is never overwritten.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from posthog.exceptions_capture import capture_exception
from posthog.models.comment import Comment

if TYPE_CHECKING:
    from posthog.models.team import Team

    from products.conversations.backend.models import Ticket

logger = structlog.get_logger(__name__)

# Per-team opt-in key inside `team.conversations_settings` (the same JSON blob that
# holds `ai_suggestions_enabled`, etc.).
SUBJECT_GENERATION_SETTING = "ai_subject_generation_enabled"

# Cheap utility model — subject lines are short, so haiku is plenty.
SUBJECT_MODEL = "claude-haiku-4-5"
MAX_SUBJECT_LENGTH = 200  # Matches Ticket.subject max_length.
SUBJECT_REQUEST_TIMEOUT_SECONDS = 30.0
# The reply we ask the model to send back when the existing subject is already good.
_KEEP_SENTINEL = "KEEP"

_SYSTEM_PROMPT = (
    "You write short, accurate subject lines for customer support tickets. "
    "A good subject is a concise noun phrase (about 3 to 8 words) capturing what the "
    "customer needs. Use sentence case, no trailing punctuation, no surrounding quotes, "
    "and no ticket numbers. Reply with only the subject line and nothing else."
)


def should_generate_subject(ticket: Ticket) -> bool:
    """Cheap, local (no network) gates deciding whether a ticket is eligible.

    Deliberately excludes the feature-flag check (a network call) so the enqueue
    path can skip non-opted-in teams without hitting the flags service; the worker
    evaluates the flag before spending on the LLM.
    """
    settings_dict = ticket.team.conversations_settings or {}
    if not settings_dict.get(SUBJECT_GENERATION_SETTING, False):
        return False

    # A human- or channel-provided subject (email tickets) is authoritative — never touch it.
    if (ticket.email_subject or "").strip():
        return False

    if not ticket.team.organization.is_ai_data_processing_approved:
        return False

    return True


def _load_conversation_text(ticket: Ticket) -> str:
    """Chronological, non-private thread rendered for the prompt."""
    # noqa: PLC0415 — suggest.py pulls in heavy HogQL query runners; keep them off the
    # import path of the request-time signal + eager task wiring that imports this module.
    from products.conversations.backend.ai.suggest import format_conversation  # noqa: PLC0415

    messages = list(
        Comment.objects.filter(
            team_id=ticket.team_id,
            scope="conversations_ticket",
            item_id=str(ticket.id),
            deleted=False,
        )
        .exclude(item_context__is_private=True)
        .order_by("created_at")
    )
    return format_conversation(ticket, messages)


def _build_messages(current_subject: str | None, conversation_text: str) -> list[dict[str, str]]:
    if current_subject:
        user = (
            f'The ticket currently has this subject: "{current_subject}".\n\n'
            f"Here is the conversation so far:\n\n{conversation_text}\n\n"
            f"If the current subject still accurately captures what the ticket is about, "
            f"reply with exactly: {_KEEP_SENTINEL}\n"
            f"Otherwise reply with a better subject line."
        )
    else:
        user = (
            f"Here is a customer support conversation:\n\n{conversation_text}\n\nWrite a concise subject line for it."
        )
    return [{"role": "system", "content": _SYSTEM_PROMPT}, {"role": "user", "content": user}]


def _clean_subject(raw: str) -> str | None:
    """Normalize the model's reply to a single clean subject line, or None to skip."""
    text = raw.strip().splitlines()[0].strip() if raw.strip() else ""
    text = text.strip().strip('"').strip("'").strip()
    if not text or text.upper() == _KEEP_SENTINEL:
        return None
    return text[:MAX_SUBJECT_LENGTH]


def generate_subject(team: Team, ticket: Ticket) -> str | None:
    """Ask the utility model for a subject line, returning None to leave it unchanged.

    None means either the thread is empty, the current subject is still good, or the
    model returned nothing usable. Raises on gateway errors — the caller decides how
    to handle transient failures.
    """
    # noqa: PLC0415 — keeps the anthropic/openai SDK imports off this module's import
    # path, which is loaded by the request-time signal wiring at django.setup().
    from posthog.llm.gateway_client import get_llm_client  # noqa: PLC0415

    conversation_text = _load_conversation_text(ticket)
    if not conversation_text.strip():
        return None

    client = get_llm_client(product="conversations", team_id=team.id)
    response = client.chat.completions.create(
        model=SUBJECT_MODEL,
        messages=_build_messages(ticket.subject, conversation_text),  # type: ignore[arg-type]
        max_tokens=64,
        temperature=0.2,
        timeout=SUBJECT_REQUEST_TIMEOUT_SECONDS,
        user=f"team-{team.id}",
        extra_headers={"x-posthog-property-ticket_id": str(ticket.id)},
    )
    choice = response.choices[0].message.content if response.choices else None
    cleaned = _clean_subject(choice or "")
    if cleaned is None or cleaned == (ticket.subject or ""):
        return None
    return cleaned


def maybe_generate_subject(ticket: Ticket) -> str | None:
    """Run the full flow for one ticket, swallowing errors (this is best-effort).

    Returns the new subject if one was produced, else None. The feature-flag check
    lives here — the local gates (`should_generate_subject`) are re-checked so the
    function is safe to call directly (e.g. from tests) without the signal path.
    """
    # Imported here to keep the flag module (and posthoganalytics) off this module's
    # import path, which is pulled in by the request-time signal wiring.
    from products.conversations.backend.feature_flags import is_ai_subject_generation_enabled  # noqa: PLC0415

    if not should_generate_subject(ticket):
        return None
    if not is_ai_subject_generation_enabled(ticket.team):
        return None
    try:
        return generate_subject(ticket.team, ticket)
    except Exception as e:
        capture_exception(e, {"ticket_id": str(ticket.id)})
        return None
