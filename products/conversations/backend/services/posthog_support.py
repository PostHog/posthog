"""Drafts of tickets to PostHog's own support team, written by a person's agent for the person to approve.

An agent stores a draft. The person then approves it in chat so the agent sends it, or sends it from the
web app's support form. Either way, a draft becomes at most one ticket.
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
from posthog.models.team import Team
from posthog.models.user import User

from products.conversations.backend.services.posthog_support_widget import SentSupportTicket

from ee.billing.billing_manager import BillingManager

DRAFT_TTL_SECONDS = 24 * 60 * 60
# The claimant an agent's send uses. A browser session claims with its session key, which never has
# this value, so the web app and the agent can never both hold a draft.
AGENT_CLAIMANT = "agent"
MAX_SEND_ATTEMPTS = 4
MAX_TICKETS_PER_TOPIC = 3
TOPIC_WINDOW_SECONDS = 72 * 60 * 60
# Redirects to the person's own region
SUPPORT_PANEL_URL = "https://app.posthog.com/home#panel=support"
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
    UNEXPLAINED_ERROR = "unexplained_error", "A reproducible error the agent confirmed but cannot explain"
    USER_DISAGREES_WITH_AGENT = "user_disagrees_with_agent", "The person disagrees with the agent's answer"


# The person already got an answer, so support needs to see that answer to settle the disagreement.
ANSWERED_FILING_REASONS = frozenset({FilingReason.USER_ASKED_FOR_SUPPORT, FilingReason.USER_DISAGREES_WITH_AGENT})


class TicketTopic(models.TextChoices):
    PRIVACY = "privacy", "Privacy"
    SECURITY = "security", "Security"
    COMPLIANCE = "compliance", "Compliance"
    RETENTION = "retention", "Data retention"
    DPA = "dpa", "Data processing agreement (DPA)"
    BAA = "baa", "Business associate agreement (BAA)"
    PRIVACY_OR_SECURITY_DELETION = (
        "privacy_or_security_deletion",
        "Deleting data for a privacy or security reason",
    )
    OTHER_DELETION = "other_deletion", "Deleting data for another reason"
    BILLING = "billing", "Billing or usage"
    OTHER = "other", "Anything else"


ANY_PLAN_TOPICS = frozenset({TicketTopic.BILLING, TicketTopic.PRIVACY_OR_SECURITY_DELETION})


class DraftedVia(models.TextChoices):
    MCP = "mcp", "Drafted by an AI agent through the PostHog MCP"
    API = "api", "Drafted through the PostHog API"


class SentVia(models.TextChoices):
    WEB_APP = "web_app", "then reviewed and sent by the person"
    # The server cannot see the person's yes in chat, so this does not claim one.
    CHAT = "chat", "then sent by the agent. PostHog did not verify the person's approval"


class TicketPermission(StrEnum):
    ALLOWED = "allowed"
    PLAN_EXCLUDES_SUPPORT = "plan_excludes_support"
    PLAN_UNKNOWN = "plan_unknown"
    TOPIC_EXCLUDED = "topic_excluded"


def _check_plan(organization: Organization, user: User) -> TicketPermission:
    """Keep this rule the same as canCreateTicket in sidepanelTicketsLogic.ts, which the web app's
    support form applies in the browser."""
    if organization.created_at > timezone.now() - relativedelta(months=NEW_ORGANIZATION_SUPPORT_MONTHS):
        return TicketPermission.ALLOWED
    instance_license = get_cached_instance_license()
    if instance_license is None:
        # Without a license there is no billing account, and the web app shows such an instance as free.
        return TicketPermission.PLAN_EXCLUDES_SUPPORT
    try:
        billing = BillingManager(instance_license, user).get_billing_read_only(
            organization, timeout=BILLING_TIMEOUT_SECONDS
        )
    except Exception as e:
        capture_exception(e)
        return TicketPermission.PLAN_UNKNOWN
    trial = billing.get("trial") or {}
    if billing.get("subscription_level") in ("paid", "custom") or (
        trial.get("status") == "active" and trial.get("target") in SUPPORT_TRIAL_TARGETS
    ):
        return TicketPermission.ALLOWED
    return TicketPermission.PLAN_EXCLUDES_SUPPORT


def check_ticket_permission(organization: Organization, user: User, topic: TicketTopic) -> TicketPermission:
    """Whether an agent can file a ticket on this topic for this organization.

    The agent picks the topic, so this limits what a well-behaved agent files. It does not stop one that
    mislabels a ticket.
    """
    if topic in ANY_PLAN_TOPICS:
        return TicketPermission.ALLOWED
    permission = _check_plan(organization, user)
    if topic == TicketTopic.OTHER and permission != TicketPermission.PLAN_EXCLUDES_SUPPORT:
        return TicketPermission.TOPIC_EXCLUDED
    return permission


@frozen
class SupportTicketDraft:
    id: str
    message: str
    topic: TicketTopic
    filing_reason: FilingReason
    expires_at: int
    drafted_via: DraftedVia = DraftedVia.API
    mcp_session_id: str | None = None
    mcp_conversation_id: str | None = None

    def ticket_context(self, sent_via: SentVia, team: Team) -> str:
        # The person cannot see or edit this note, so it holds only text the server writes. The MCP ids
        # come from request headers, so the API keeps a value only when it has the form of an id.
        lines = [
            f"{DraftedVia(self.drafted_via).label}, {sent_via.label}.",
            f"Topic: {TicketTopic(self.topic).label}.",
            f"Why it was drafted: {FilingReason(self.filing_reason).label}.",
            f"Organization id: {team.organization_id}",
            f"Project id: {team.id}",
            f"Draft id: {self.id}",
        ]
        # Support finds the agent's tool calls by these ids, under $mcp_session_id and $mcp_conversation_id.
        if self.mcp_session_id:
            lines.append(f"MCP session id: {self.mcp_session_id}")
        if self.mcp_conversation_id:
            lines.append(f"MCP conversation id: {self.mcp_conversation_id}")
        return "\n".join(lines)

    def outgoing_message(self, sent_via: SentVia, team: Team) -> str:
        # The same layout as appendTicketContext in supportLogic.ts, so support sees one shape whichever
        # way the ticket was sent.
        return f"{self.message}\n\n-----\n{self.ticket_context(sent_via, team)}"


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
    # Plain labels, not Markdown bold, because the web app's form shows the draft in a plain text box.
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
    """Short-lived drafts that wait for the person to review and send them. A draft belongs to one person
    and one project, so a ticket always names the project it was drafted for."""

    def __init__(self, user_id: int, team_id: int) -> None:
        self._user_id = user_id
        self._owner = f"{user_id}:{team_id}"
        self._cache = caches["posthog_support_drafts"]

    def create(
        self,
        *,
        message: str,
        topic: TicketTopic,
        filing_reason: FilingReason,
        drafted_via: DraftedVia = DraftedVia.API,
        mcp_session_id: str | None = None,
        mcp_conversation_id: str | None = None,
    ) -> SupportTicketDraft:
        draft = SupportTicketDraft(
            id=str(uuid.uuid4()),
            message=message,
            topic=topic,
            filing_reason=filing_reason,
            expires_at=int(time.time()) + DRAFT_TTL_SECONDS,
            drafted_via=drafted_via,
            mcp_session_id=mcp_session_id,
            mcp_conversation_id=mcp_conversation_id,
        )
        self._cache.set(self._key(draft.id), {**asdict(draft), "topic": topic.value}, DRAFT_TTL_SECONDS)
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
            topic=TicketTopic(stored["topic"]),
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
        """Give back a claim after a send that created no ticket, so the web app can send it."""
        if self._cache.get(self._claim_key(draft_id)) == claimant:
            self._cache.delete(self._claim_key(draft_id))

    def count_send_attempt(self, draft_id: str) -> int:
        self._cache.add(self._attempts_key(draft_id), 0, DRAFT_TTL_SECONDS)
        return self._cache.incr(self._attempts_key(draft_id))

    def send_started(self, draft_id: str) -> bool:
        return self._cache.get(self._sending_key(draft_id)) is not None

    def start_send(self, draft_id: str) -> bool:
        """Mark a server-side send as running. Only one send can run. A send with an unknown result
        keeps the mark until the draft expires, because a retry could create a second ticket."""
        return bool(self._cache.add(self._sending_key(draft_id), 1, DRAFT_TTL_SECONDS))

    def cancel_send(self, draft_id: str) -> None:
        self._cache.delete(self._sending_key(draft_id))

    def record_sent(self, draft_id: str, topic: TicketTopic, ticket: SentSupportTicket) -> None:
        self._cache.set(self._sent_key(draft_id), asdict(ticket), DRAFT_TTL_SECONDS)
        sent_at = [*self._recent_sends(topic), int(time.time())]
        self._cache.set(self._topic_key(topic), sent_at, TOPIC_WINDOW_SECONDS)

    def topic_limit_reached(self, topic: TicketTopic) -> bool:
        return len(self._recent_sends(topic)) >= MAX_TICKETS_PER_TOPIC

    def _recent_sends(self, topic: TicketTopic) -> list[int]:
        oldest = time.time() - TOPIC_WINDOW_SECONDS
        return [sent_at for sent_at in self._cache.get(self._topic_key(topic)) or [] if sent_at > oldest]

    def sent_ticket(self, draft_id: str) -> SentSupportTicket | None:
        stored = self._cache.get(self._sent_key(draft_id))
        if stored is None:
            return None
        return SentSupportTicket(ticket_id=stored["ticket_id"], ticket_number=stored.get("ticket_number"))

    def _topic_key(self, topic: TicketTopic) -> str:
        # Not per project, so switching projects does not reset the limit
        return f"posthog_support_topic_sends:{self._user_id}:{topic.value}"

    def _attempts_key(self, draft_id: str) -> str:
        return f"posthog_support_draft_attempts:{self._owner}:{draft_id}"

    def _sending_key(self, draft_id: str) -> str:
        return f"posthog_support_draft_sending:{self._owner}:{draft_id}"

    def _sent_key(self, draft_id: str) -> str:
        return f"posthog_support_draft_sent:{self._owner}:{draft_id}"

    def _claim_key(self, draft_id: str) -> str:
        return f"posthog_support_draft_claim:{self._owner}:{draft_id}"

    def _key(self, draft_id: str) -> str:
        return f"posthog_support_draft:{self._owner}:{draft_id}"
