from typing import Any

from structlog import get_logger

from posthog.temporal.data_imports.signals.registry import SignalEmitterOutput, SignalSourceTableConfig

logger = get_logger(__name__)

# We don't want to analyze tickets that were already solved
ZENDESK_IGNORED_STATUSES = ("closed", "solved")

# Injecting ticket description into the prompt could cause a security issue, but it should be covered by the Signals pipeline checks
ZENDESK_ACTIONABILITY_PROMPT = """You are a product feedback analyst. Given a customer support ticket, determine if it contains actionable product feedback.

A ticket is ACTIONABLE if it describes:
- A bug, error, or unexpected behavior in the product
- A feature request or suggestion for improvement
- A usability issue or confusion about the product
- A performance problem

A ticket is NOT_ACTIONABLE if it is:
- Spam, abuse, or profanity with no real feedback
- A billing/account question with no product feedback
- A generic "thank you" or "how do I" question answerable by docs
- An auto-generated or bot message

Ticket:
```
{description}
```

Respond with exactly one word: ACTIONABLE or NOT_ACTIONABLE"""

# Fields the emitter needs to build the signal description
REQUIRED_FIELDS = ("id", "subject", "description", "priority", "status")

# Additional metadata to attach to the signal
EXTRA_FIELDS = ("url", "type", "tags", "created_at", "requester_id", "organization_id", "brand_id")


def zendesk_ticket_emitter(team_id: int, record: dict[str, Any]) -> SignalEmitterOutput | None:
    # Required fields based on `zendesk_tickets` table definition
    ticket_id = record.get("id")
    subject = record.get("subject")
    description = record.get("description")
    # Not enough meaningful data to emit a signal
    if not ticket_id or not subject or not description:
        logger.warning(
            f"Not enough meaningful data to emit a signal for ticket {ticket_id}",
            # Including full record for proper context
            record=record,
            signals_type="zendesk_ticket",
        )
        return None
    priority = record.get("priority")
    status = record.get("status")
    # Build a rich description for embedding
    signal_description = f"New Zendesk ticket: {subject}.\nDescription: {description}."
    if status:
        signal_description += f"\nStatus: {status}."
    if priority:
        # TODO: Decide if to define signal weight based on priority
        signal_description += f"\nPriority: {priority}."
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
)
