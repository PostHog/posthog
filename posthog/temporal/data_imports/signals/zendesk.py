from typing import Any

from posthog.temporal.data_imports.signals.registry import SignalEmitterOutput, SignalSourceConfig

# We don't want to analyze tickets that were already solved
ZENDESK_IGNORED_STATUSES = ("closed", "solved")


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
    signal_description = f"New Zendesk ticket: {subject}. Description: {description}."
    if priority:
        # TODO: Define weight based on priority?
        signal_description += f" Priority: {priority}"
    if status:
        signal_description += f" Status: {status}"
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
)
