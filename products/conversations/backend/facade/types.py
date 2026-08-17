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


@dataclass(frozen=True)
class EmailThreadAccountLinkInput:
    account_id: str
    account_external_id: str | None
    match_source: str


@dataclass(frozen=True)
class EmailThreadForAccountMatching:
    id: str
    participant_emails: list[str]


@dataclass(frozen=True)
class EmailThreadParticipantSummary:
    email: str
    display_name: str
    kind: str


@dataclass(frozen=True)
class AccountEmailThreadSummary:
    id: str
    subject: str
    preview: str
    first_message_at: datetime | None
    last_message_at: datetime | None
    message_count: int
    participants: list[EmailThreadParticipantSummary]


@dataclass(frozen=True)
class EmailThreadAddress:
    name: str
    email: str


@dataclass(frozen=True)
class AccountEmailThreadMessage:
    id: str
    sent_at: datetime
    sender: EmailThreadAddress
    to_recipients: list[EmailThreadAddress]
    cc_recipients: list[EmailThreadAddress]
    sender_authenticated: bool
    direction: str
    content: str
