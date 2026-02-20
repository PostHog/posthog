from typing import Any

from structlog import get_logger

from posthog.temporal.data_imports.signals.registry import SignalEmitterOutput, SignalSourceTableConfig

logger = get_logger(__name__)

# We don't want to analyze tickets that were already solved
ZENDESK_IGNORED_STATUSES = ("closed", "solved")

ZENDESK_SUMMARIZATION_PROMPT = """Summarize this support ticket into a concise description for semantic search.
Capture the core problem or request, the product area affected, and any relevant context like error messages or what the customer already tried.
Strip email signatures, legal disclaimers, and system-generated footers — but keep quoted replies or conversation fragments if they add context about the issue.
Keep the summary under {max_length} characters. Respond with only the summary text.

<ticket>
{description}
</ticket>
"""

ZENDESK_ACTIONABILITY_PROMPT = """You are a product feedback analyst. Given a customer support ticket, determine if it contains actionable product feedback.

A ticket is ACTIONABLE if it describes:
- A bug, error, or unexpected behavior in the product (including billing/payment bugs like wrong charges or coupons not applied)
- A feature request or suggestion for improvement
- A usability issue or confusion about the product
- A performance problem
- A question about the product or product integrations
- An ask to help with the product
- and similar cases

A ticket is NOT_ACTIONABLE if it is:
- Spam, abuse, or profanity with no real feedback
- A routine billing/account question that does NOT indicate a product bug (e.g. requesting a refund, updating payment info, asking about pricing)
- A generic "thank you"
- An auto-generated or bot message
- An internal test message

When in doubt, classify as ACTIONABLE. It is much worse to miss real feedback than to let some noise through.

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
    "requester_id",
    "organization_id",
    "brand_id",
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
        logger.exception(msg, record=record, team_id=team_id)
        raise ValueError(msg) from e
    if not ticket_id or not subject or not description:
        msg = f"Zendesk ticket record has empty required field: id={ticket_id!r}, subject={subject!r}, description={description!r}"
        logger.exception(msg, record=record, team_id=team_id)
        raise ValueError(msg)
    signal_description = f"{subject}\n{description}"
    return SignalEmitterOutput(
        source_type="zendesk_ticket",
        source_id=str(ticket_id),
        description=signal_description,
        # Sticking to 1 by default for user-generated issues
        weight=1.0,
        # Attach only the fields that would make sense for a signal, without duplicating already included data
        extra={k: v for k, v in record.items() if k in EXTRA_FIELDS},
    )


ZENDESK_TICKETS_CONFIG = SignalSourceTableConfig(
    emitter=zendesk_ticket_emitter,
    partition_field="created_at",
    fields=REQUIRED_FIELDS + EXTRA_FIELDS,
    where_clause=f"status NOT IN ({', '.join(repr(s) for s in ZENDESK_IGNORED_STATUSES)})",
    max_records=100,
    first_sync_lookback_days=7,
    actionability_prompt=ZENDESK_ACTIONABILITY_PROMPT,
    summarization_prompt=ZENDESK_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
