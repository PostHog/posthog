"""Where a provider conversation is remembered between sends.

A resolve replies to the message that fired rather than posting beside it, which needs the
handle from that first send. The store holds that handle, and holds what makes a redelivery
safe: no provider offers an idempotency key, so a send a crash left unrecorded repeats on
retry unless the row says it already happened.

The key carries the firing as well, which the RFC's own shape does not. Without it the table
holds one row per alert instead of one per firing, and there is no version of that decision
under which a second firing should reply into the first firing's thread.

It carries no `notification_key`. That field only ever differs from the group once fan-in
ships, and fan-in was deprioritized on 2026-09-28, so the group is what identifies a
conversation until then.
"""

from datetime import datetime, timedelta
from typing import Protocol

from django.db import models
from django.utils import timezone

from posthog.dataclasses import frozen

from products.alerts_platform.backend.delivery.transport import MessageHandle
from products.alerts_platform.backend.models import PlatformAlertThread

# How long a send may hold a conversation before another attempt may take it. Long enough to
# cover a provider's own timeout, so a retry that starts while the first attempt is still
# posting waits rather than posting a second copy.
PENDING_CLAIM_TTL = timedelta(minutes=2)

# A thread lives as long as its firing, and the list only has to outlive a retry.
DELIVERED_KEYS_CAP = 20


@frozen
class ThreadKey:
    """Which conversation a message belongs to.

    Two parts carry that. `grouping_key` separates one group's conversation from another's, and
    `episode_started_at` separates one firing from the next. Without the episode a key names the
    alert rather than the firing, so every resolve an alert ever sends replies into the thread
    its first firing opened. Without the group, two groups of one configuration share a thread.

    One object rather than five arguments, because four of the parts are strings and a caller
    that passes them separately can reorder them without a typecheck noticing.
    """

    configuration_id: str
    grouping_key: str
    provider: str
    channel_target: str
    episode_started_at: datetime


@frozen
class ThreadClaim:
    """A conversation held for the duration of one send.

    `handle` is what to reply to, and is None when this send opens the conversation.
    `claimed_at` fences the release: an attempt that outlived the TTL and was superseded must
    not clear its successor's claim or record its own send over the successor's.
    """

    thread_id: str
    evaluation_key: str
    handle: MessageHandle | None
    claimed_at: datetime


class ThreadBusy(Exception):
    """Another send holds this conversation and has not finished with it."""


class ThreadStore(Protocol):
    def claim(self, key: ThreadKey, evaluation_key: str) -> ThreadClaim | None:
        """Take the conversation for one send, or None when it already carried this evaluation.

        Raises `ThreadBusy` when another send holds it and the hold is still fresh.
        """
        ...

    def delivered(self, claim: ThreadClaim, handle: MessageHandle | None) -> None: ...

    def release(self, claim: ThreadClaim) -> None: ...


class NullThreadStore:
    """Remembers nothing, so every message is a new one and no send is ever skipped.

    Not a regression where nothing is wired: the platform sends nothing today. It does mean a
    resolve posts beside the message that fired rather than under it, and that a retry after a
    crash sends again.
    """

    def claim(self, key: ThreadKey, evaluation_key: str) -> ThreadClaim | None:
        return ThreadClaim(thread_id="", evaluation_key=evaluation_key, handle=None, claimed_at=timezone.now())

    def delivered(self, claim: ThreadClaim, handle: MessageHandle | None) -> None:
        return None

    def release(self, claim: ThreadClaim) -> None:
        return None


class DatabaseThreadStore:
    """`PlatformAlertThread` as the conversation store.

    Three states decide whether a send happens, in this order: already delivered, held by a
    live claim, free. Reading them in any other order would let a retry of an evaluation that
    already landed take a claim it does not need.
    """

    def __init__(self, team_id: int) -> None:
        self._team_id = team_id

    def claim(self, key: ThreadKey, evaluation_key: str) -> ThreadClaim | None:
        thread, _ = PlatformAlertThread.objects.for_team(self._team_id).get_or_create(
            configuration_id=key.configuration_id,
            grouping_key=key.grouping_key,
            provider=key.provider,
            channel_target=key.channel_target,
            episode_started_at=key.episode_started_at,
            defaults={"team_id": self._team_id},
        )
        if evaluation_key in (thread.delivered_evaluation_keys or []):
            return None

        now = timezone.now()
        # One conditional UPDATE rather than a read and a write: two attempts reading a free
        # claim at the same moment would both believe they held it. Every write here sets
        # `updated_at` itself, because `QuerySet.update()` skips `auto_now`.
        taken = (
            PlatformAlertThread.objects.for_team(self._team_id)
            .filter(id=thread.id)
            .filter(
                models.Q(pending_evaluation_key__isnull=True) | models.Q(pending_claimed_at__lt=now - PENDING_CLAIM_TTL)
            )
            .update(pending_evaluation_key=evaluation_key, pending_claimed_at=now, updated_at=now)
        )
        if not taken:
            raise ThreadBusy(f"thread {thread.id} is being posted to by another send")

        handle = MessageHandle(external_ref=thread.external_ref) if thread.external_ref else None
        return ThreadClaim(thread_id=str(thread.id), evaluation_key=evaluation_key, handle=handle, claimed_at=now)

    def delivered(self, claim: ThreadClaim, handle: MessageHandle | None) -> None:
        thread = PlatformAlertThread.objects.for_team(self._team_id).filter(id=claim.thread_id).first()
        if thread is None:
            return
        delivered = [*(thread.delivered_evaluation_keys or []), claim.evaluation_key][-DELIVERED_KEYS_CAP:]
        fields: dict[str, object] = {
            "delivered_evaluation_keys": delivered,
            "pending_evaluation_key": None,
            "pending_claimed_at": None,
            "updated_at": timezone.now(),
        }
        # Only the message that opened the conversation is remembered. Recording a reply would
        # move the thread onto itself, so a later message would reply to a reply.
        if handle is not None and not thread.external_ref:
            fields["external_ref"] = handle.external_ref
        self._fenced(claim).update(**fields)

    def release(self, claim: ThreadClaim) -> None:
        self._fenced(claim).update(pending_evaluation_key=None, pending_claimed_at=None, updated_at=timezone.now())

    def _fenced(self, claim: ThreadClaim) -> models.QuerySet[PlatformAlertThread]:
        return PlatformAlertThread.objects.for_team(self._team_id).filter(
            id=claim.thread_id, pending_claimed_at=claim.claimed_at
        )
