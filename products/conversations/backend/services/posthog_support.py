"""Contact PostHog's own support team on behalf of a logged-in user.

Tickets live in PostHog's support project, which may sit in another region, so reads go through
that project's public widget API with the same signed identity the in-app support panel uses.
Nothing here files a ticket. An agent can only stash a draft, and only the web app's support
form, driven by the person, sends it.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict
from typing import Any

from django.conf import settings
from django.core.cache import cache
from django.db import models

import requests
import structlog

from posthog.dataclasses import frozen
from posthog.models.instance_setting import get_instance_setting
from posthog.models.user import User
from posthog.utils import resolve_self_flags_team

from products.conversations.backend.services.identity import (
    SignedIdentity,
    sign_identity,
    widget_session_id_for_identity,
)

logger = structlog.get_logger(__name__)

WIDGET_REQUEST_TIMEOUT_SECONDS = 10
DRAFT_TTL_SECONDS = 24 * 60 * 60
# A person reviews each draft by hand, so a long list of open drafts means an agent is looping.
MAX_OPEN_DRAFTS_PER_USER = 5
UNREACHABLE_MESSAGE = "PostHog support could not be reached. Try again shortly."
# Every read spends the support project's shared widget budget, which the in-app support panel
# also polls from, so repeat reads from an agent are served from here instead.
READ_CACHE_SECONDS = 60
# The widget's own message when it refuses a ticket the identity does not own. Any other refusal
# means the identity itself failed verification.
_NOT_OWNER_ERROR = "Forbidden"


class FilingReason(models.TextChoices):
    # Each reason starts from what the person wants or what only PostHog can see, never from the
    # agent's own diagnosis, so an agent cannot file just because it decided the bug is ours.
    USER_ASKED_FOR_SUPPORT = "user_asked_for_support", "The person asked to contact PostHog support"
    ACCOUNT_OR_BILLING = "account_or_billing", "Account, billing or data only PostHog can see"
    UNEXPLAINED_ERROR = "unexplained_error", "A reproducible error the agent confirmed but cannot explain"
    USER_DISAGREES_WITH_AGENT = "user_disagrees_with_agent", "The person disagrees with the agent's answer"


class PostHogSupportUnavailable(Exception):
    """The support project cannot be reached from this instance, or this user has no identity for it."""


class PostHogSupportTicketNotFound(Exception):
    pass


class TooManyOpenDrafts(Exception):
    pass


class DraftCreateInProgress(Exception):
    pass


@frozen
class SupportWidgetTarget:
    host: str
    token: str


@frozen
class SupportTicketSummary:
    id: str
    ticket_number: int | None
    status: str
    unread_count: int
    last_message: str | None
    last_message_at: str | None
    message_count: int
    created_at: str


@frozen
class SupportTicketPage:
    count: int
    results: list[SupportTicketSummary]


@frozen
class SupportTicketMessage:
    id: str
    content: str
    author_type: str
    author_name: str
    created_at: str


@frozen
class SupportTicketThread:
    ticket_id: str
    ticket_status: str
    messages: list[SupportTicketMessage]
    has_more: bool


@frozen
class SupportTicketDraft:
    id: str
    message: str
    filing_reason: FilingReason
    agent_name: str | None
    expires_at: int

    @property
    def ticket_context(self) -> str:
        """The note support reads under the ticket, saying an agent drafted it and why."""
        agent = f" ({self.agent_name})" if self.agent_name else ""
        return (
            f"Drafted by an AI agent{agent} through the PostHog MCP, then reviewed and sent by the person.\n"
            f"Why the agent drafted it: {FilingReason(self.filing_reason).label}.\n"
            f"Draft id: {self.id}"
        )


def build_support_identity(user: User) -> SignedIdentity:
    secret = get_instance_setting("CONVERSATIONS_HMAC_SIGNING_SECRET")
    if not secret or not user.distinct_id:
        raise PostHogSupportUnavailable("Support identity signing is not configured on this instance.")
    verified_email = user.email if user.is_email_verified is True else None
    return sign_identity(user.distinct_id, secret, verified_email=verified_email)


def _identity_params(identity: SignedIdentity) -> dict[str, str]:
    params = {
        "identity_distinct_id": identity.distinct_id,
        "identity_hash": identity.hash,
        # The widget throttles identity requests by IP unless a session id is present. Every user
        # reaches it from this server's IP, so key the throttle per user instead.
        "widget_session_id": widget_session_id_for_identity(identity.hash),
    }
    if identity.email:
        params["identity_email"] = identity.email.value
        params["identity_hash_email"] = identity.email.hash
        params["identity_exp_email"] = str(identity.email.expires_at)
    return params


def resolve_support_widget_target() -> SupportWidgetTarget:
    if settings.POSTHOG_SUPPORT_WIDGET_TOKEN:
        return SupportWidgetTarget(
            host=settings.POSTHOG_SUPPORT_WIDGET_HOST.rstrip("/"), token=settings.POSTHOG_SUPPORT_WIDGET_TOKEN
        )

    if settings.SELF_CAPTURE:
        team = resolve_self_flags_team()
        token = ((team.conversations_settings or {}).get("widget_public_token") if team else None) or ""
        if token:
            return SupportWidgetTarget(host=settings.SITE_URL.rstrip("/"), token=token)

    raise PostHogSupportUnavailable("PostHog support is not configured on this instance.")


class PostHogSupportClient:
    def __init__(self, target: SupportWidgetTarget, identity: SignedIdentity) -> None:
        self._target = target
        self._distinct_id = identity.distinct_id
        self._params = _identity_params(identity)

    def list_tickets(self, *, status: str | None, limit: int, offset: int) -> SupportTicketPage:
        params: dict[str, Any] = {**self._params, "limit": limit, "offset": offset}
        if status:
            params["status"] = status
        # A list call is only refused when the identity fails verification, which is a setup problem.
        data = self._get(
            "/api/conversations/v1/widget/tickets",
            params,
            cache_key=f"tickets:{status}:{limit}:{offset}",
            on_not_owner=PostHogSupportUnavailable,
        )
        return SupportTicketPage(
            count=data.get("count", 0),
            results=[
                SupportTicketSummary(
                    id=row["id"],
                    ticket_number=row.get("ticket_number"),
                    status=row["status"],
                    unread_count=row.get("unread_count") or 0,
                    last_message=row.get("last_message"),
                    last_message_at=row.get("last_message_at"),
                    message_count=row.get("message_count") or 0,
                    created_at=row["created_at"],
                )
                for row in data.get("results", [])
            ],
        )

    def get_thread(self, ticket_id: str) -> SupportTicketThread:
        # The widget refuses a ticket the identity does not own. Report that as not found, so a
        # caller cannot probe for other people's ticket ids.
        data = self._get(
            f"/api/conversations/v1/widget/messages/{ticket_id}",
            self._params,
            cache_key=f"messages:{ticket_id}",
            on_not_owner=PostHogSupportTicketNotFound,
        )
        return SupportTicketThread(
            ticket_id=data["ticket_id"],
            ticket_status=data["ticket_status"],
            messages=[
                SupportTicketMessage(
                    id=m["id"],
                    content=m.get("content") or "",
                    author_type=m.get("author_type") or "customer",
                    author_name=m.get("author_name") or "",
                    created_at=m["created_at"],
                )
                for m in data.get("messages", [])
            ],
            has_more=bool(data.get("has_more")),
        )

    def _get(
        self, path: str, params: dict[str, Any], *, cache_key: str, on_not_owner: type[Exception]
    ) -> dict[str, Any]:
        full_cache_key = f"posthog_support_read:{self._distinct_id}:{cache_key}"
        cached = cache.get(full_cache_key)
        if cached is not None:
            return cached

        try:
            response = requests.get(
                f"{self._target.host}{path}",
                params=params,
                headers={"X-Conversations-Token": self._target.token},
                timeout=WIDGET_REQUEST_TIMEOUT_SECONDS,
            )
        except requests.RequestException as e:
            logger.warning("posthog_support_widget_request_failed", path=path, error=str(e))
            raise PostHogSupportUnavailable(UNREACHABLE_MESSAGE) from e

        if response.status_code == 404:
            raise on_not_owner(UNREACHABLE_MESSAGE)
        if response.status_code == 403:
            if _widget_error(response) == _NOT_OWNER_ERROR:
                raise on_not_owner(UNREACHABLE_MESSAGE)
            logger.warning("posthog_support_identity_rejected", path=path, error=_widget_error(response))
            raise PostHogSupportUnavailable(UNREACHABLE_MESSAGE)
        if not response.ok:
            logger.warning("posthog_support_widget_bad_status", path=path, status=response.status_code)
            raise PostHogSupportUnavailable(UNREACHABLE_MESSAGE)
        data = response.json()
        cache.set(full_cache_key, data, READ_CACHE_SECONDS)
        return data


def _widget_error(response: requests.Response) -> str | None:
    try:
        return response.json().get("error")
    except ValueError:
        return None


class SupportDraftStore:
    """Short-lived, per-user drafts of tickets an agent prepared for a person to review and send."""

    def __init__(self, user_id: int) -> None:
        self._user_id = user_id

    def create(self, *, message: str, filing_reason: FilingReason, agent_name: str | None) -> SupportTicketDraft:
        # The cap check and the index write must not interleave, or parallel calls each pass the
        # check and the last index write drops the others' drafts from the count.
        lock_key = f"posthog_support_drafts_lock:{self._user_id}"
        if not cache.add(lock_key, 1, timeout=10):
            raise DraftCreateInProgress()
        try:
            return self._create(message=message, filing_reason=filing_reason, agent_name=agent_name)
        finally:
            cache.delete(lock_key)

    def _create(self, *, message: str, filing_reason: FilingReason, agent_name: str | None) -> SupportTicketDraft:
        # The index can name drafts that were sent, discarded or expired. Only live ones count.
        indexed = cache.get(self._index_key()) or []
        live = cache.get_many([self._key(draft_id) for draft_id in indexed])
        open_ids = [draft_id for draft_id in indexed if self._key(draft_id) in live]
        if len(open_ids) >= MAX_OPEN_DRAFTS_PER_USER:
            raise TooManyOpenDrafts()

        draft = SupportTicketDraft(
            id=str(uuid.uuid4()),
            message=message,
            filing_reason=filing_reason,
            agent_name=agent_name,
            expires_at=int(time.time()) + DRAFT_TTL_SECONDS,
        )
        cache.set_many(
            {self._key(draft.id): asdict(draft), self._index_key(): [*open_ids, draft.id]}, DRAFT_TTL_SECONDS
        )
        return draft

    def get(self, draft_id: str) -> SupportTicketDraft | None:
        # Stored as a plain dict, so a draft written before a deploy still loads after it.
        stored = cache.get(self._key(draft_id))
        if stored is None:
            return None
        return SupportTicketDraft(
            id=stored["id"],
            message=stored["message"],
            filing_reason=stored["filing_reason"],
            agent_name=stored.get("agent_name"),
            expires_at=stored["expires_at"],
        )

    def delete(self, draft_id: str) -> bool:
        """Remove a draft. Atomic, so exactly one of two concurrent callers gets True."""
        return bool(cache.delete(self._key(draft_id)))

    def _index_key(self) -> str:
        return f"posthog_support_drafts:{self._user_id}"

    def _key(self, draft_id: str) -> str:
        return f"posthog_support_draft:{self._user_id}:{draft_id}"


def compose_draft_message(*, customer_words: str, details: str | None, already_tried: str | None) -> str:
    """Lay out the ticket body the way support reads it: the customer's own words first."""
    sections = [("In my words", customer_words), ("Details", details), ("What I already tried", already_tried)]
    return "\n\n".join(f"{title}:\n{body.strip()}" for title, body in sections if body and body.strip())
