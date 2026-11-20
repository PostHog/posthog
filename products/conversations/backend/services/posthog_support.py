"""Drafts of tickets to PostHog's own support team, written by a person's agent for the person to approve.

An agent stores a draft. The person then sends it from the web app's support form, or approves it in
chat so the agent sends it. Either way, a draft becomes at most one ticket.
"""

from __future__ import annotations

import re
import time
import uuid
from dataclasses import asdict
from enum import StrEnum

from django.core.cache import caches
from django.db import models
from django.utils import timezone

from dateutil.relativedelta import relativedelta

from posthog.cloud_utils import get_cached_instance_license
from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception
from posthog.models.organization import Organization
from posthog.models.user import User

from products.conversations.backend.services.posthog_support_widget import SentSupportTicket

from ee.billing.billing_manager import BillingManager

DRAFT_TTL_SECONDS = 24 * 60 * 60
# The claimant an agent's send uses. A browser session claims with its session key, which never has
# this value, so the review link and the agent can never both hold a draft.
AGENT_CLAIMANT = "agent"
NEW_ORGANIZATION_SUPPORT_MONTHS = 3
SUPPORT_TRIAL_TARGETS = frozenset({"boost", "scale", "enterprise"})
BILLING_TIMEOUT_SECONDS = (3.0, 5.0)
# Renders as a horizontal line. It needs the blank lines, because `---` right under text turns that
# text into a Markdown heading. The support form finds sections by this string to place images.
SECTION_SEPARATOR = "\n\n---\n\n"


class FilingReason(models.TextChoices):
    # Each reason starts from what the person wants or what only PostHog can see, never from the
    # agent's own diagnosis, so an agent cannot file just because it decided the bug is ours.
    USER_ASKED_FOR_SUPPORT = "user_asked_for_support", "The person asked to contact PostHog support"
    NEEDS_POSTHOG_STAFF = "needs_posthog_staff", "Only PostHog staff can do or see what the person needs"
    BILLING_QUESTION = "billing_question", "A billing or usage question, which PostHog answers on every plan"
    UNEXPLAINED_ERROR = "unexplained_error", "A reproducible error the agent confirmed but cannot explain"
    USER_DISAGREES_WITH_AGENT = "user_disagrees_with_agent", "The person disagrees with the agent's answer"


class DraftedVia(models.TextChoices):
    MCP = "mcp", "Drafted by an AI agent through the PostHog MCP"
    API = "api", "Drafted through the PostHog API"


class SentVia(models.TextChoices):
    WEB_APP = "web_app", "then reviewed and sent by the person"
    CHAT = "chat", "then sent by the agent after the person approved it in chat"


class TicketPermission(StrEnum):
    ALLOWED = "allowed"
    PLAN_EXCLUDES_SUPPORT = "plan_excludes_support"
    PLAN_UNKNOWN = "plan_unknown"


def check_ticket_permission(organization: Organization, user: User, filing_reason: str) -> TicketPermission:
    """Whether the organization's plan lets it open a ticket with PostHog support.

    Keep this rule the same as canCreateTicket in sidepanelTicketsLogic.ts, which the web app's
    support form applies in the browser.
    """
    if filing_reason == FilingReason.BILLING_QUESTION:
        return TicketPermission.ALLOWED
    if organization.created_at > timezone.now() - relativedelta(months=NEW_ORGANIZATION_SUPPORT_MONTHS):
        return TicketPermission.ALLOWED
    instance_license = get_cached_instance_license()
    if instance_license is None:
        # Without a license there is no billing account, and the web app shows such an instance as free.
        return TicketPermission.PLAN_EXCLUDES_SUPPORT
    try:
        billing = BillingManager(instance_license, user).get_billing(organization, timeout=BILLING_TIMEOUT_SECONDS)
    except Exception as e:
        capture_exception(e)
        return TicketPermission.PLAN_UNKNOWN
    trial = billing.get("trial") or {}
    if billing.get("subscription_level") in ("paid", "custom") or (
        trial.get("status") == "active" and trial.get("target") in SUPPORT_TRIAL_TARGETS
    ):
        return TicketPermission.ALLOWED
    return TicketPermission.PLAN_EXCLUDES_SUPPORT


@frozen
class SupportTicketDraft:
    id: str
    message: str
    filing_reason: FilingReason
    expires_at: int
    drafted_via: DraftedVia = DraftedVia.API
    mcp_session_id: str | None = None
    mcp_conversation_id: str | None = None

    def ticket_context(self, sent_via: SentVia) -> str:
        # The person cannot see or edit this note, so it holds only text the server writes. The MCP ids
        # come from request headers, so the API keeps a value only when it has the form of an id.
        lines = [
            f"{DraftedVia(self.drafted_via).label}, {sent_via.label}.",
            f"Why it was drafted: {FilingReason(self.filing_reason).label}.",
            f"Draft id: {self.id}",
        ]
        # Support finds the agent's tool calls by these ids, under $mcp_session_id and $mcp_conversation_id.
        if self.mcp_session_id:
            lines.append(f"MCP session id: {self.mcp_session_id}")
        if self.mcp_conversation_id:
            lines.append(f"MCP conversation id: {self.mcp_conversation_id}")
        return "\n".join(lines)

    def outgoing_message(self, sent_via: SentVia) -> str:
        # The same layout as appendTicketContext in supportLogic.ts, so support sees one shape whichever
        # way the ticket was sent.
        return f"{self.message}\n\n-----\n{self.ticket_context(sent_via)}"


def compose_ticket_message(
    *,
    title: str,
    request: str,
    details: str | None = None,
    already_checked: str | None = None,
    error: str | None = None,
) -> str:
    """Lay the ticket out in the shape the writing-posthog-support-tickets skill teaches, so every
    agent-drafted ticket reads the same way to support."""
    # Plain labels, not Markdown bold, because the person reviews the draft in a plain text box.
    sections = [
        ("Request", request),
        ("Details", details),
        ("Already checked", already_checked),
        ("Error", error),
    ]
    # Ticket lists preview a ticket by its first line, so the title goes first, on a line of its own
    parts = [" ".join(title.split())]
    for label, body in sections:
        if not body or not body.strip():
            continue
        body = body.strip()
        if label == "Error":
            body = _code_block(body)
        # Markdown joins two lines of prose into one paragraph, so Request needs a blank line to render its
        # label on its own line. The other sections open with a list, which starts a new block anyway.
        separator = "\n\n" if label == "Request" else "\n"
        parts.append(f"{label}:{separator}{body}")
    return SECTION_SEPARATOR.join(parts)


def _code_block(text: str) -> str:
    """Shows error text exactly as given. As Markdown, a line that starts with `#` or `*` would become a
    heading or a list item, and the indentation of stack frames would be lost."""
    if text.startswith("```") and text.endswith("```"):
        return text
    # The fence must be longer than any run of backticks in the text, or that run would close it early.
    longest_run = max((len(run) for run in re.findall(r"`+", text)), default=0)
    fence = "`" * max(3, longest_run + 1)
    return f"{fence}text\n{text}\n{fence}"


class SupportDraftStore:
    """Short-lived, per-user drafts that wait for the person to review and send them."""

    def __init__(self, user_id: int) -> None:
        self._user_id = user_id
        self._cache = caches["posthog_support_drafts"]

    def create(
        self,
        *,
        message: str,
        filing_reason: FilingReason,
        drafted_via: DraftedVia = DraftedVia.API,
        mcp_session_id: str | None = None,
        mcp_conversation_id: str | None = None,
    ) -> SupportTicketDraft:
        draft = SupportTicketDraft(
            id=str(uuid.uuid4()),
            message=message,
            filing_reason=filing_reason,
            expires_at=int(time.time()) + DRAFT_TTL_SECONDS,
            drafted_via=drafted_via,
            mcp_session_id=mcp_session_id,
            mcp_conversation_id=mcp_conversation_id,
        )
        self._cache.set(self._key(draft.id), asdict(draft), DRAFT_TTL_SECONDS)
        return draft

    def get(self, draft_id: str, *, claimant: str | None = None) -> SupportTicketDraft | None:
        """A draft nobody claimed yet, or one this claimant claimed."""
        found = self._cache.get_many([self._key(draft_id), self._claim_key(draft_id)])
        stored = found.get(self._key(draft_id))
        claimed_by = found.get(self._claim_key(draft_id))
        if stored is None or (claimed_by is not None and claimed_by != claimant):
            return None
        # Stored as a plain dict, so a draft written before a deploy still loads after it.
        return SupportTicketDraft(
            id=stored["id"],
            message=stored["message"],
            filing_reason=stored["filing_reason"],
            expires_at=stored["expires_at"],
            # A draft saved before this field existed keeps the note it was created with, which named the MCP
            drafted_via=stored.get("drafted_via", DraftedVia.MCP),
            mcp_session_id=stored.get("mcp_session_id"),
            mcp_conversation_id=stored.get("mcp_conversation_id"),
        )

    def claim(self, draft_id: str, claimant: str) -> bool:
        """Reserve a draft for one browser session to send. The same session can claim again, so a
        retry after a lost response still works, but no other session can."""
        if self.get(draft_id, claimant=claimant) is None:
            return False
        return bool(self._cache.add(self._claim_key(draft_id), claimant, DRAFT_TTL_SECONDS)) or (
            self._cache.get(self._claim_key(draft_id)) == claimant
        )

    def release(self, draft_id: str, claimant: str) -> None:
        """Give back a claim after a send that created no ticket, so the review link works again."""
        if self._cache.get(self._claim_key(draft_id)) == claimant:
            self._cache.delete(self._claim_key(draft_id))

    def start_send(self, draft_id: str) -> bool:
        """Mark a server-side send as running. Only one send can run. A send with an unknown result
        keeps the mark until the draft expires, because a retry could create a second ticket."""
        return bool(self._cache.add(self._sending_key(draft_id), 1, DRAFT_TTL_SECONDS))

    def cancel_send(self, draft_id: str) -> None:
        self._cache.delete(self._sending_key(draft_id))

    def record_sent(self, draft_id: str, ticket: SentSupportTicket) -> None:
        self._cache.set(self._sent_key(draft_id), asdict(ticket), DRAFT_TTL_SECONDS)

    def sent_ticket(self, draft_id: str) -> SentSupportTicket | None:
        stored = self._cache.get(self._sent_key(draft_id))
        if stored is None:
            return None
        return SentSupportTicket(ticket_id=stored["ticket_id"], ticket_number=stored.get("ticket_number"))

    def _sending_key(self, draft_id: str) -> str:
        return f"posthog_support_draft_sending:{self._user_id}:{draft_id}"

    def _sent_key(self, draft_id: str) -> str:
        return f"posthog_support_draft_sent:{self._user_id}:{draft_id}"

    def _claim_key(self, draft_id: str) -> str:
        return f"posthog_support_draft_claim:{self._user_id}:{draft_id}"

    def _key(self, draft_id: str) -> str:
        return f"posthog_support_draft:{self._user_id}:{draft_id}"
