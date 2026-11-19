"""Drafts of tickets to PostHog's own support team, written by a person's agent for the person to send.

Nothing here files a ticket. An agent stores a draft, and only the web app's support form, driven by
the person in their browser, sends it.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict

from django.core.cache import caches
from django.db import models

from posthog.dataclasses import frozen

DRAFT_TTL_SECONDS = 24 * 60 * 60
# A person reviews each draft by hand, so a long list of open drafts means an agent is looping.
MAX_OPEN_DRAFTS_PER_USER = 5


class FilingReason(models.TextChoices):
    # Each reason starts from what the person wants or what only PostHog can see, never from the
    # agent's own diagnosis, so an agent cannot file just because it decided the bug is ours.
    USER_ASKED_FOR_SUPPORT = "user_asked_for_support", "The person asked to contact PostHog support"
    NEEDS_POSTHOG_STAFF = "needs_posthog_staff", "Only PostHog staff can do or see what the person needs"
    UNEXPLAINED_ERROR = "unexplained_error", "A reproducible error the agent confirmed but cannot explain"
    USER_DISAGREES_WITH_AGENT = "user_disagrees_with_agent", "The person disagrees with the agent's answer"


class TooManyOpenDrafts(Exception):
    pass


class DraftCreateInProgress(Exception):
    pass


@frozen
class SupportTicketDraft:
    id: str
    message: str
    filing_reason: FilingReason
    expires_at: int

    @property
    def ticket_context(self) -> str:
        # The person cannot see or edit this note, so it holds only text the server writes.
        return (
            "Drafted by an AI agent through the PostHog MCP, then reviewed and sent by the person.\n"
            f"Why the agent drafted it: {FilingReason(self.filing_reason).label}.\n"
            f"Draft id: {self.id}"
        )


def compose_ticket_message(
    *,
    request: str,
    left_for_support: str,
    details: str | None = None,
    already_checked: str | None = None,
    error: str | None = None,
) -> str:
    """Lay the ticket out in the shape the writing-posthog-support-tickets skill teaches, so every
    agent-drafted ticket reads the same way to support."""
    # Plain labels, not Markdown bold, because the person reviews the draft in a plain text box.
    one_line_titles = {"Request", "Left for support"}
    sections = [
        ("Request", request),
        ("Details", details),
        ("Already checked", already_checked),
        ("Left for support", left_for_support),
        ("Error", error),
    ]
    parts = []
    for title, body in sections:
        if not body or not body.strip():
            continue
        separator = " " if title in one_line_titles else "\n"
        parts.append(f"{title}:{separator}{body.strip()}")
    return "\n\n".join(parts)


class SupportDraftStore:
    """Short-lived, per-user drafts that wait for the person to review and send them."""

    def __init__(self, user_id: int) -> None:
        self._user_id = user_id
        self._cache = caches["posthog_support_drafts"]

    def create(self, *, message: str, filing_reason: FilingReason) -> SupportTicketDraft:
        # The cap check and the index write must not interleave, or parallel calls each pass the
        # check and the last index write drops the others' drafts from the count.
        lock_key = f"posthog_support_drafts_lock:{self._user_id}"
        if not self._cache.add(lock_key, 1, timeout=10):
            raise DraftCreateInProgress()
        try:
            return self._create(message=message, filing_reason=filing_reason)
        finally:
            self._cache.delete(lock_key)

    def _create(self, *, message: str, filing_reason: FilingReason) -> SupportTicketDraft:
        # The index can name drafts that were sent or expired. Only unclaimed live ones count.
        indexed = self._cache.get(self._index_key()) or []
        found = self._cache.get_many(
            [self._key(draft_id) for draft_id in indexed] + [self._claim_key(draft_id) for draft_id in indexed]
        )
        open_ids = [
            draft_id for draft_id in indexed if self._key(draft_id) in found and self._claim_key(draft_id) not in found
        ]
        if len(open_ids) >= MAX_OPEN_DRAFTS_PER_USER:
            raise TooManyOpenDrafts()

        draft = SupportTicketDraft(
            id=str(uuid.uuid4()),
            message=message,
            filing_reason=filing_reason,
            expires_at=int(time.time()) + DRAFT_TTL_SECONDS,
        )
        self._cache.set_many(
            {self._key(draft.id): asdict(draft), self._index_key(): [*open_ids, draft.id]}, DRAFT_TTL_SECONDS
        )
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
        )

    def claim(self, draft_id: str, claimant: str) -> bool:
        """Reserve a draft for one browser session to send. The same session can claim again, so a
        retry after a lost response still works, but no other session can."""
        if self.get(draft_id, claimant=claimant) is None:
            return False
        return bool(self._cache.add(self._claim_key(draft_id), claimant, DRAFT_TTL_SECONDS)) or (
            self._cache.get(self._claim_key(draft_id)) == claimant
        )

    def _claim_key(self, draft_id: str) -> str:
        return f"posthog_support_draft_claim:{self._user_id}:{draft_id}"

    def _index_key(self) -> str:
        return f"posthog_support_drafts:{self._user_id}"

    def _key(self, draft_id: str) -> str:
        return f"posthog_support_draft:{self._user_id}:{draft_id}"
