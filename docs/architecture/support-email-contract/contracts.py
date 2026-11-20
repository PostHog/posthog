"""Draft contracts for the two seams. Prototype only: this file never merges.

Seam 1: Conversations outbox -> Messaging code send (in-process facade, regional by deployment).
Seam 2: Workflows inbound intake -> Conversations email ingest.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

# --- Seam 1: send -----------------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class ReplyHeaders:
    # Bounded by Workflows to SES header limits: keeps the first and the newest ids when References is long.
    in_reply_to: str | None
    references: tuple[str, ...]
    # Only the forwarding verification email sets this. Its body carries the same token.
    forwarding_challenge: str | None = None


class EmailStream(StrEnum):
    # Picks the SES configuration set. SUPPORT forces tracking off, sensitive on and no sandbox fallback.
    DEFAULT = "default"
    SUPPORT = "support"


# Added to messaging's existing CodeEmail (facade/contracts.py:232):
#   headers: ReplyHeaders | None = None
#   stream: EmailStream = EmailStream.DEFAULT
#
# Existing entry point, unchanged signature (services/transactional_email.py:681):
#   send_code_email(team, email: CodeEmail, *, to, distinct_id, idempotency_key) -> QueuedEmail
#
# Invariants
# - idempotency_key = f"conversations-outbox:{outbox.id}". Same key and same payload replay the first
#   QueuedEmail, so the outbox snapshots the rendered payload on its first attempt.
# - Workflows keeps idempotency records for SUPPORT longer than the outbox max age (5 days).
# - headers are part of the idempotency fingerprint.
# - QueuedEmail.message_id is the Workflows send id. It is not the RFC Message-ID; SES sets that.
#
# Error modes, and what the outbox does
# - DeliveryUnavailable, IdempotencyKeyInFlight  -> retry with the same key (backoff as today)
# - SenderNotVerified (new, code "sender_not_verified") -> mark the channel unverified, fail the row
# - IdempotencyKeyReused                         -> a send already queued under this key: mark sent
# - other TransactionalEmailError                -> fail the row permanently


@dataclass(frozen=True, kw_only=True)
class SentMessageMatch:
    wire_message_id: str  # the RFC Message-ID SES put on the wire
    send_id: str  # QueuedEmail.message_id


def match_sent_message_ids(team_id: int, message_ids: tuple[str, ...]) -> tuple[SentMessageMatch, ...]:
    """Messaging facade. Which of these RFC Message-IDs are sends of this team.

    Conversations calls it when its own EmailMessageMapping misses, then maps send_id -> outbox -> ticket.
    Empty for ids Workflows never sent. Team-scoped. One indexed read per inbound message.
    """
    raise NotImplementedError


# --- Seam 2: receive --------------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class ReceiptVerdicts:
    # From the SNS-signed SES receipt, never from MIME headers.
    spf: str
    dkim: str
    dmarc: str
    spam: str
    virus: str
    sender_verified: bool  # DMARC pass, or SPF pass aligned with From


@dataclass(frozen=True, kw_only=True)
class InboundAttachment:
    filename: str
    content_type: str
    content: bytes
    content_id: str
    inline: bool


@dataclass(frozen=True, kw_only=True)
class InboundEmail:
    """Workflows-owned. Handed to a registered mailbox route before Workflows' own filters and persistence."""

    ses_message_id: str  # delivery identity; the route must be idempotent on it
    envelope_to: str  # the matched recipient, which carries the team-<token>@ local part
    envelope_from: str
    received_at: datetime
    verdicts: ReceiptVerdicts
    message_id: str
    in_reply_to: str
    references: tuple[str, ...]
    from_address: str
    from_name: str
    to_addresses: tuple[str, ...]
    cc_addresses: tuple[str, ...]
    subject: str
    text: str
    html: str
    reply_text: str  # quoted history removed; signatures kept
    headers: tuple[tuple[str, str], ...]  # all headers, bounded, for challenge tokens and DKIM signer tags
    attachments: tuple[InboundAttachment, ...]
    auto_submitted: bool


class RouteOutcome(StrEnum):
    INGESTED = "ingested"
    DUPLICATE = "duplicate"
    IGNORED = "ignored"  # no channel, disabled, self-addressed autoreply


class TransientRouteError(Exception):
    """Workflows keeps the S3 intake object and redelivers."""


def register_mailbox_route(domain_setting: str, local_part_pattern: str, handler: str) -> None:
    """Workflows facade, called from Conversations' app config. Workflows never imports Conversations."""
    raise NotImplementedError


# Conversations side: one provider-neutral entry, fed by the Mailgun, SES and Gmail adapters.
#   ingest_email(team_id: int, channel_id: UUID, envelope_to: str, email: ParsedEmail) -> RouteOutcome
# where ParsedEmail is products/conversations/backend/services/email_thread_ingestion.py:45 with
# attachments as bounded byte values instead of Django UploadedFile.
