from typing import Any

from structlog import get_logger

from posthog.temporal.data_imports.signals.fetchers.conversations import conversations_ticket_fetcher
from posthog.temporal.data_imports.signals.registry import SignalEmitterOutput, SignalSourceTableConfig

logger = get_logger(__name__)

CONVERSATIONS_SUMMARIZATION_PROMPT = """Summarize this support conversation for semantic search.
Output exactly two parts separated by a newline:
1. A short title (under 100 characters) that captures the core issue or request
2. A concise summary capturing the problem or request, the product area affected, and any relevant context like error messages, what the customer tried, or how the team responded

Strip email signatures, legal disclaimers, and system-generated footers.
Keep the total output under {max_length} characters. Respond with only the title and summary, nothing else.

<conversation>
{description}
</conversation>
"""

CONVERSATIONS_ACTIONABILITY_PROMPT = """You are a product feedback analyst. Given a support conversation, determine if it contains feedback that engineers could address with code changes (bug fixes, new features, performance improvements, etc.).

A conversation is ACTIONABLE if it describes:
- A bug, error, or unexpected behavior in the product
- A feature request or suggestion for improvement
- A usability issue or confusion about the product
- A performance problem
- A question about the product or product integrations
- An ask to help with the product
- and similar cases

A conversation is NOT_ACTIONABLE if it is:
- Spam, abuse, or profanity with no real feedback
- A generic "thank you" or confirmation that an issue was resolved
- An auto-generated, bot, or out-of-office message
- An internal test message
- A conversation whose primary ask is a manual human action, not a code change (e.g. requesting a refund, updating payment method, asking about pricing)

When in doubt, classify as ACTIONABLE. It is worse to miss real feedback than to let some noise through.

<conversation>
{description}
</conversation>

Respond with exactly one word: ACTIONABLE or NOT_ACTIONABLE"""

# Keep recent messages within this budget before handing to LLM.
# Generous enough for most threads; prevents pathological email chains from blowing up cost/latency.
MAX_DESCRIPTION_CHARS = 10_000

REQUIRED_FIELDS = ("id",)

EXTRA_FIELDS = (
    "ticket_number",
    "channel_source",
    "channel_detail",
    "status",
    "priority",
    "created_at",
    "email_subject",
)


def conversations_ticket_emitter(team_id: int, record: dict[str, Any]) -> SignalEmitterOutput | None:
    try:
        ticket_id = record["id"]
    except KeyError as e:
        msg = f"Conversations ticket record missing required field {e}"
        logger.exception(msg, record=record, team_id=team_id, signals_type="conversations-signals")
        raise ValueError(msg) from e
    if not ticket_id:
        msg = f"Conversations ticket record has empty required field: id={ticket_id!r}"
        logger.exception(msg, record=record, team_id=team_id, signals_type="conversations-signals")
        raise ValueError(msg)
    messages: list[tuple[str, str]] = record.get("messages", [])
    if not messages:
        logger.info(
            "Ignoring conversations ticket without messages",
            ticket_id=ticket_id,
            team_id=team_id,
            signals_type="conversations-signals",
        )
        return None
    # Prefix each message with a short author tag so turns are distinguishable
    # without adding much embedding noise. C = customer, T = team member, AI = bot.
    tagged_lines = [f"{_author_tag(author)}: {content}" for author, content in messages]
    # Keep most recent messages within char budget (recent turns are most relevant)
    tagged_lines = _truncate_to_budget(tagged_lines, MAX_DESCRIPTION_CHARS)
    email_subject = record.get("email_subject")
    if email_subject:
        signal_description = f"{email_subject}\n" + "\n".join(tagged_lines)
    else:
        signal_description = "\n".join(tagged_lines)
    return SignalEmitterOutput(
        source_product="conversations",
        source_type="ticket",
        source_id=str(ticket_id),
        description=signal_description,
        weight=1.0,
        extra=_build_extra(record),
    )


_AUTHOR_TAGS = {"customer": "C", "team": "T", "support": "T", "AI": "AI"}


def _author_tag(author_type: str) -> str:
    return _AUTHOR_TAGS.get(author_type, "T")


def _truncate_to_budget(lines: list[str], budget: int) -> list[str]:
    """Keep the first message (the issue description) plus the most recent lines that fit."""
    if not lines:
        return []
    # Everything fits
    if sum(len(line) for line in lines) <= budget:
        return lines
    first = lines[0]
    if len(first) >= budget:
        # If the first message is huge
        return [first[:budget]]
    if len(lines) == 1:
        # If just one message
        return [first]
    remaining_budget = budget - len(first)
    # Pick messages from the end
    tail: list[str] = []
    for line in reversed(lines[1:]):
        if remaining_budget - len(line) < 0:
            break
        tail.append(line)
        remaining_budget -= len(line)
    # Restore the original order
    tail.reverse()
    return [first, *tail]


def _build_extra(record: dict[str, Any]) -> dict[str, Any]:
    extra: dict[str, Any] = {field: record[field] for field in EXTRA_FIELDS if field in record}
    # Image URLs are publicly fetchable — surface them so the research agent can inspect them directly
    image_attachments = record.get("image_attachments") or []
    if image_attachments:
        extra["images"] = image_attachments
    return extra


CONVERSATIONS_TICKETS_CONFIG = SignalSourceTableConfig(
    source_product="conversations",
    source_type="ticket",
    emitter=conversations_ticket_emitter,
    record_fetcher=conversations_ticket_fetcher,
    partition_field="created_at",
    fields=REQUIRED_FIELDS + EXTRA_FIELDS,
    where_clause="status != 'resolved'",
    max_records=100,
    first_sync_lookback_days=30,
    actionability_prompt=CONVERSATIONS_ACTIONABILITY_PROMPT,
    summarization_prompt=CONVERSATIONS_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
