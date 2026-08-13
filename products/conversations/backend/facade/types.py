"""Contract types other products receive from the conversations facade.

Frozen dataclasses only — no ORM objects or slack_sdk types cross the boundary.

Named types.py, not the conventional contracts.py, because that filename is what
`hogli product:lint` reads as "this product is isolated" and conversations isn't
yet. Rename it once the product meets the strict structure rules.
"""

from datetime import datetime

from pydantic.dataclasses import dataclass


@dataclass(frozen=True)
class SupportChannel:
    """A Slack channel visible to the SupportHog bot."""

    id: str
    name: str
    is_member: bool


@dataclass(frozen=True)
class TicketSummary:
    """A support ticket, reduced to what an account's tickets list renders."""

    id: str
    ticket_number: int
    status: str
    last_message_at: datetime | None
    last_message_text: str | None
    deep_link: str
