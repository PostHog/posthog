"""Idempotency guard for team-authored support messages.

Two POST paths create them, and both get retried in the wild: gateways and API clients replay
the request within a second, and an operator whose send looks like it failed sends the same text
again. Dedupe on the validated request the server already has, so neither caller needs to supply
an idempotency key.

Redis access goes through ``posthog.redis.get_client()`` rather than the Django cache. The default
cache alias is replica-aware, so the ``GET`` that follows a lost ``SET NX`` could read a lagging
replica and report a conflict for a reservation that already resolved. This client is bound to
``REDIS_URL`` alone, and it exposes the Lua needed for the owner-token compares below, which
``cache.add``/``get``/``set`` cannot do atomically.
"""

import json
import uuid
import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Any

from django.utils import timezone

import structlog

from posthog.models.comment import Comment
from posthog.redis import get_client

logger = structlog.get_logger(__name__)

# A reservation only has to outlive one request, and a worker killed mid-create self-heals this
# many seconds later instead of blocking that exact message for the full replay window.
IN_FLIGHT_TTL_SECONDS = 30
# How long a created message stays replayable. Covers the automated retries (0-1s apart) and the
# operator who resends after an unconfirmed send (tens of seconds).
REPLAY_WINDOW_SECONDS = 120

SUPPORT_TICKET_SCOPE = "conversations_ticket"
SUPPORT_AUTHOR_TYPE = "support"

REPLY_IN_PROGRESS_ERROR_TYPE = "reply_in_progress"
REPLY_IN_PROGRESS_DETAIL = "This message is already being sent. Check the thread before sending it again."

# Both endpoints hash into one keyspace, so a retry that switches paths still replays. Bump the
# version when the fingerprint's contents change, so old entries can't be read under new rules.
_KEY_PREFIX = "conversations:reply_dedupe:v1:"
_IN_FLIGHT_VALUE_PREFIX = "inflight:"
_COMMENT_VALUE_PREFIX = "comment:"

# Compare the owner token before writing, so a creator that stalled past its own TTL cannot
# overwrite or delete the reservation a later attempt has since taken.
_PUBLISH_SCRIPT = """
if redis.call('GET', KEYS[1]) ~= ARGV[1] then
    return 0
end
redis.call('SET', KEYS[1], ARGV[2], 'EX', ARGV[3])
return 1
"""

_RELEASE_SCRIPT = """
if redis.call('GET', KEYS[1]) ~= ARGV[1] then
    return 0
end
return redis.call('DEL', KEYS[1])
"""


class ReservationState(Enum):
    # Free to create, either because we took the reservation or because Redis couldn't answer.
    ACQUIRED = "acquired"
    # Another attempt holds the reservation and hasn't finished creating yet.
    IN_FLIGHT = "in_flight"
    # An earlier attempt already created this message.
    REPLAY = "replay"


@dataclass(frozen=True, kw_only=True)
class Reservation:
    state: ReservationState
    key: str
    # Absent when we failed open, which makes publish and release no-ops.
    owner_token: str | None = None
    comment_id: str | None = None


@dataclass(frozen=True, kw_only=True)
class ReplyFingerprint:
    """The immutable identity of a support-message create request.

    Two requests with the same fingerprint are the same message: same team, ticket, author,
    thread position, body, and privacy. ``build`` returns None for anything this guard must not
    collapse.
    """

    team_id: int
    scope: str
    item_id: str
    created_by_id: int
    source_comment_id: str | None
    content: str
    rich_content: Any
    item_context: dict[str, Any]

    @classmethod
    def build(
        cls,
        *,
        team_id: int,
        created_by_id: int | None,
        scope: Any,
        item_id: Any,
        content: Any,
        rich_content: Any,
        item_context: Any,
        source_comment_id: Any = None,
        is_task: Any = False,
        has_unverifiable_metadata: bool = False,
    ) -> "ReplyFingerprint | None":
        if scope != SUPPORT_TICKET_SCOPE or not item_id or created_by_id is None:
            return None
        if not isinstance(item_context, dict) or item_context.get("author_type") != SUPPORT_AUTHOR_TYPE:
            return None
        # A task carries state (completion) that a replayed response would misreport, and an emoji
        # reaction is a toggle rather than a message.
        if is_task or item_context.get("is_emoji"):
            return None
        # Explicit mentions and the notification slug are consumed by the serializer and never
        # persisted, so a replay can't confirm the stored row came from the same request.
        if has_unverifiable_metadata:
            return None
        if not isinstance(content, str):
            return None

        return cls(
            team_id=team_id,
            scope=scope,
            item_id=str(item_id),
            created_by_id=created_by_id,
            source_comment_id=str(source_comment_id) if source_comment_id else None,
            content=content,
            rich_content=rich_content,
            item_context=item_context,
        )

    @property
    def key(self) -> str:
        canonical = json.dumps(
            {
                "team_id": self.team_id,
                "scope": self.scope,
                "item_id": self.item_id,
                "created_by_id": self.created_by_id,
                "source_comment_id": self.source_comment_id,
                "content": self.content,
                "rich_content": self.rich_content,
                "item_context": self.item_context,
            },
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        # Only the digest reaches Redis, so no message content lands in a key.
        return f"{_KEY_PREFIX}{hashlib.sha256(canonical.encode()).hexdigest()}"

    def matches(self, comment: Comment) -> bool:
        """Whether this persisted comment is the message this request asked for."""
        if comment.deleted or comment.version != 0:
            return False
        if (
            comment.team_id != self.team_id
            or comment.scope != self.scope
            or comment.item_id != self.item_id
            or comment.created_by_id != self.created_by_id
            or comment.content != self.content
            or comment.rich_content != self.rich_content
        ):
            return False
        if str(comment.source_comment_id or "") != (self.source_comment_id or ""):
            return False
        # Delivery bookkeeping is merged into item_context after creation, so require the
        # request's own fields rather than equality.
        persisted_context = comment.item_context or {}
        return all(persisted_context.get(field) == value for field, value in self.item_context.items())

    def find_persisted_match(self, *, created_after: datetime) -> Comment | None:
        """The most recent row this request would have created, if some earlier attempt already did.

        This is what closes the window where a create commits but its publication never lands: the
        reservation is gone, so only the database can tell the retry that its message exists.
        """
        candidates = Comment.objects.filter(
            team_id=self.team_id,
            scope=self.scope,
            item_id=self.item_id,
            created_by_id=self.created_by_id,
            content=self.content,
            deleted=False,
            version=0,
            created_at__gte=created_after,
        ).order_by("-created_at")[:20]
        return next((comment for comment in candidates if self.matches(comment)), None)

    def load_replay_target(self, comment_id: str | None) -> Comment | None:
        """Re-verify a published mapping before serving it as a replay."""
        if not comment_id:
            return None
        comment = Comment.objects.filter(team_id=self.team_id, pk=comment_id).first()
        if comment is None or not self.matches(comment):
            logger.warning("conversations_reply_dedupe_stale_mapping", comment_id=comment_id)
            return None
        return comment


class CreateOutcome(Enum):
    CREATED = "created"
    # An identical message already exists; return it without writing anything.
    REPLAYED = "replayed"
    # A concurrent request is still creating this message, and we can't yet say which row it is.
    CONFLICT = "conflict"


@dataclass(frozen=True, kw_only=True)
class GuardedCreate:
    outcome: CreateOutcome
    comment: Comment | None = None


def create_deduplicated(fingerprint: ReplyFingerprint, create: Callable[[], Comment]) -> GuardedCreate:
    """Run ``create`` at most once per fingerprint, and report what happened.

    Both support-message endpoints go through here so the protocol can't drift between them. The
    caller owns the response shape: a REPLAYED outcome is theirs to render as a 200 and a CONFLICT
    as a 409. Exceptions from ``create`` propagate unchanged after the reservation is settled.
    """
    reservation = reserve(fingerprint)
    if reservation.state is ReservationState.REPLAY:
        replayed = fingerprint.load_replay_target(reservation.comment_id)
        if replayed is not None:
            return GuardedCreate(outcome=CreateOutcome.REPLAYED, comment=replayed)
        # A mapping we can't verify is treated as no mapping, rather than serving an unrelated row.
    elif reservation.state is ReservationState.IN_FLIGHT:
        return GuardedCreate(outcome=CreateOutcome.CONFLICT)

    attempted_at = timezone.now()
    already_created = fingerprint.find_persisted_match(created_after=_replay_window_start(attempted_at))
    if already_created is not None:
        publish(reservation, already_created.id)
        return GuardedCreate(outcome=CreateOutcome.REPLAYED, comment=already_created)

    try:
        comment = create()
    except Exception:
        # Mention fan-out and post_save receivers run after the INSERT, so an exception does not
        # mean the row is absent. Releasing blindly would make an already-delivered message
        # immediately repeatable.
        recovered = fingerprint.find_persisted_match(created_after=attempted_at)
        if recovered is not None:
            publish(reservation, recovered.id)
        else:
            release(reservation)
        raise

    publish(reservation, comment.id)
    return GuardedCreate(outcome=CreateOutcome.CREATED, comment=comment)


def _replay_window_start(attempted_at: datetime) -> datetime:
    return attempted_at - timedelta(seconds=REPLAY_WINDOW_SECONDS)


def reserve(fingerprint: ReplyFingerprint) -> Reservation:
    """Claim the right to create this message, or report who got there first.

    Fails open (ACQUIRED without a token) once Redis has failed twice. That degrades to the caller's
    recent-row lookup, which catches a retry of a message that already committed. It does not
    serialize two concurrent first attempts: while Redis is unreachable, both can pass that lookup
    before either inserts, and the customer receives the message twice. Closing that last race needs
    a durable idempotency key or a uniqueness constraint, which this design deliberately avoids, so
    the retry here is what keeps a single dropped connection from widening the window.
    """
    key = fingerprint.key
    token = f"{_IN_FLIGHT_VALUE_PREFIX}{uuid.uuid4()}"
    for attempt in range(2):
        try:
            client = get_client()
            if client.set(key, token, nx=True, ex=IN_FLIGHT_TTL_SECONDS):
                return Reservation(state=ReservationState.ACQUIRED, key=key, owner_token=token)
            held = client.get(key)
            if held is not None:
                return _classify_held_value(key, held, token)
            # The holder's entry expired or was evicted between the SET and the GET, so try again
            # instead of reporting a conflict that no longer exists.
        except Exception:
            if attempt == 0:
                continue
            logger.warning("conversations_reply_dedupe_reserve_error", key=key, exc_info=True)
    return Reservation(state=ReservationState.ACQUIRED, key=key)


def publish(reservation: Reservation, comment_id: Any) -> None:
    """Point the reservation at the created message so later retries replay it."""
    if reservation.owner_token is None:
        return
    value = f"{_COMMENT_VALUE_PREFIX}{comment_id}"
    for attempt in range(2):
        try:
            get_client().eval(
                _PUBLISH_SCRIPT, 1, reservation.key, reservation.owner_token, value, REPLAY_WINDOW_SECONDS
            )
            return
        except Exception:
            if attempt == 0:
                continue
            # The message is already committed. Raising here would turn a confirmed send into an
            # error the client is likely to retry, and the recent-row lookup covers that retry.
            logger.exception("conversations_reply_dedupe_publish_failed", key=reservation.key)


def release(reservation: Reservation) -> None:
    """Give up the reservation so an immediate retry isn't blocked for the full in-flight TTL."""
    if reservation.owner_token is None:
        return
    try:
        get_client().eval(_RELEASE_SCRIPT, 1, reservation.key, reservation.owner_token)
    except Exception:
        logger.warning("conversations_reply_dedupe_release_error", key=reservation.key, exc_info=True)


def _classify_held_value(key: str, held: Any, token: str) -> Reservation:
    value = held.decode() if isinstance(held, bytes) else str(held)
    if value == token:
        # Our own SET landed even though its reply never reached us, so we still own the reservation.
        return Reservation(state=ReservationState.ACQUIRED, key=key, owner_token=token)
    if value.startswith(_COMMENT_VALUE_PREFIX):
        return Reservation(
            state=ReservationState.REPLAY,
            key=key,
            comment_id=value.removeprefix(_COMMENT_VALUE_PREFIX),
        )
    if value.startswith(_IN_FLIGHT_VALUE_PREFIX):
        return Reservation(state=ReservationState.IN_FLIGHT, key=key)
    logger.warning("conversations_reply_dedupe_malformed_value", key=key)
    return Reservation(state=ReservationState.ACQUIRED, key=key)
