from typing import Any

from posthog.temporal.data_imports.signals.registry import SignalEmitterOutput, SignalSourceConfig

# We don't want to analyze tickets that were already solved
ZENDESK_IGNORED_STATUSES = ("closed", "solved")

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
{description}

Respond with exactly one word: ACTIONABLE or NOT_ACTIONABLE"""


def zendesk_ticket_emitter(team_id: int, record: dict[str, Any]) -> SignalEmitterOutput | None:
    # Required fields based on `zendesk_tickets` table definition
    ticket_id = record.get("id")
    subject = record.get("subject")
    description = record.get("description")
    # Not enough meaningful data to emit a signal
    if not ticket_id or not subject or not description:
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
        weight=1.0,  # Sticking to 1 by default for user-generated issues
        extra=record,  # Attach all available fields as additional context, just in case
    )


ZENDESK_TICKETS_CONFIG = SignalSourceConfig(
    emitter=zendesk_ticket_emitter,
    where_clause=f"status NOT IN {ZENDESK_IGNORED_STATUSES!r}",
    first_sync_limit=100,
    first_sync_lookback_days=7,
    actionability_prompt=ZENDESK_ACTIONABILITY_PROMPT,
)
