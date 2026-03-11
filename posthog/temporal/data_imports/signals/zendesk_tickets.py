import json
from typing import Any

from structlog import get_logger

from posthog.temporal.data_imports.signals.registry import SignalEmitterOutput, SignalSourceTableConfig

logger = get_logger(__name__)

# We don't want to analyze tickets that were already solved
ZENDESK_IGNORED_STATUSES = ("closed", "solved")

ZENDESK_SUMMARIZATION_PROMPT = """Summarize this support ticket for semantic search.
Output exactly two parts separated by a newline:
1. A short title (under 100 characters) that captures the core issue
2. A concise summary capturing the problem or request, the product area affected, and any relevant context like error messages or what the customer already tried

Strip email signatures, legal disclaimers, and system-generated footers — but keep quoted replies or conversation fragments if they add context about the issue.
Keep the total output under {max_length} characters. Respond with only the title and summary, nothing else.

<ticket>
{description}
</ticket>
"""

ZENDESK_ACTIONABILITY_PROMPT = """You are a product feedback analyst. Given a customer support ticket, determine if it contains feedback that engineers could address with code changes (bug fixes, new features, performance improvements, etc.).

A ticket is ACTIONABLE if it describes:
- A bug, error, or unexpected behavior in the product (including billing bugs where the product itself malfunctioned, e.g. a coupon code not being applied by the system, checkout flow crashing)
- A feature request or suggestion for improvement
- A usability issue or confusion about the product
- A performance problem
- A question about the product or product integrations
- An ask to help with the product
- and similar cases

A ticket is NOT_ACTIONABLE if it is:
- Spam, abuse, or profanity with no real feedback
- Tickets whose primary ask is a manual human action, not a code change (e.g. requesting a refund, updating payment method or billing email, asking about pricing, plan changes, invoice questions). Even if the user provides context explaining why they want the action, the ticket is still NOT_ACTIONABLE if the ask itself is manual
- A generic "thank you" or confirmation that an issue was resolved
- An auto-generated, bot, or out-of-office message
- An internal test message

When in doubt, classify as ACTIONABLE. It is worse to miss real feedback than to let some noise through.

<ticket>
{description}
</ticket>

Respond with exactly one word: ACTIONABLE or NOT_ACTIONABLE"""

# Fields the emitter needs to build the signal description
REQUIRED_FIELDS = ("id", "subject", "description")

# Additional metadata to attach to the signal
EXTRA_FIELDS = (
    "url",
    "type",
    "tags",
    "created_at",
    "priority",
    "status",
)


def zendesk_ticket_emitter(team_id: int, record: dict[str, Any]) -> SignalEmitterOutput | None:
    try:
        ticket_id = record["id"]
        subject = record["subject"]
        description = record["description"]
    except KeyError as e:
        msg = f"Zendesk ticket record missing required field {e}"
        logger.exception(msg, record=record, team_id=team_id, signals_type="data-import-signals")
        raise ValueError(msg) from e
    if not ticket_id or not description:
        msg = f"Zendesk ticket record has empty required field: id={ticket_id!r}, description={description!r}"
        logger.exception(msg, record=record, team_id=team_id, signals_type="data-import-signals")
        raise ValueError(msg)
    if not subject:
        # Ignore tickets without a subject
        logger.info(
            "Ignoring Zendesk ticket without a subject",
            record=record,
            team_id=team_id,
            signals_type="data-import-signals",
        )
        return None
    signal_description = f"{subject}\n{description}"
    return SignalEmitterOutput(
        source_product="zendesk",
        source_type="ticket",
        source_id=str(ticket_id),
        description=signal_description,
        weight=1.0,
        extra=_build_extra(record),
    )


def _build_extra(record: dict[str, Any]) -> dict[str, Any]:
    extra = {k: v for k, v in record.items() if k in EXTRA_FIELDS}
    raw_tags = extra.get("tags")
    if raw_tags is None:
        extra["tags"] = []
    elif isinstance(raw_tags, str):
        try:
            parsed = json.loads(raw_tags)
        except (json.JSONDecodeError, TypeError) as e:
            msg = f"Zendesk ticket tags field is not valid JSON: {raw_tags!r}"
            logger.exception(msg, record=record, signals_type="data-import-signals")
            raise ValueError(msg) from e
        if not isinstance(parsed, list):
            msg = f"Zendesk ticket tags field is not a JSON array: {raw_tags!r}"
            logger.exception(msg, record=record, signals_type="data-import-signals")
            raise ValueError(msg)
        extra["tags"] = parsed
    else:
        msg = f"Zendesk ticket tags field has unexpected type {type(raw_tags).__name__}: {raw_tags!r}"
        logger.exception(msg, record=record, signals_type="data-import-signals")
        raise ValueError(msg)
    return extra


ZENDESK_TICKETS_CONFIG = SignalSourceTableConfig(
    emitter=zendesk_ticket_emitter,
    partition_field="created_at",
    fields=REQUIRED_FIELDS + EXTRA_FIELDS,
    where_clause=f"status NOT IN ({', '.join(repr(s) for s in ZENDESK_IGNORED_STATUSES)})",
    max_records=100,
    first_sync_lookback_days=30,
    actionability_prompt=ZENDESK_ACTIONABILITY_PROMPT,
    summarization_prompt=ZENDESK_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
