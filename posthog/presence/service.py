"""
Ephemeral "who is here right now" presence, keyed on a `scope` + `item_id` pair the same loose way
`Comment` and `ActivityLog` attach to arbitrary objects.

State is a sorted set of client ids scored by last-seen timestamp, plus a hash holding each
client's payload. The score doubles as the expiry: a client that stops beating drops out of every
read once it falls behind the cutoff, so a closed tab self-heals without needing a goodbye.
Both keys share one hash tag so a pipeline over the pair is legal on a Redis cluster.

Presence is lossy by design and must never break the page it decorates — every Redis failure
degrades to "nobody is here".
"""

import json
import dataclasses
from datetime import UTC, datetime, timedelta
from typing import Literal, cast, get_args

import structlog
import redis.exceptions as redis_exceptions

from posthog import redis as redis_module

logger = structlog.get_logger(__name__)

PRESENCE_INDEX_KEY_PATTERN = "presence:{{{team_id}:{scope}:{item_id}}}:index"
PRESENCE_META_KEY_PATTERN = "presence:{{{team_id}:{scope}:{item_id}}}:meta"

# A viewer whose last heartbeat is older than this is treated as gone. Must comfortably exceed the
# client's heartbeat interval so one dropped request doesn't make an avatar flicker.
PRESENCE_TTL_SECONDS = 30
# Whole-key backstop, so an item nobody is on any more leaves nothing behind.
PRESENCE_KEY_TTL_SECONDS = 300
# 'composing' decays back to 'viewing' server-side too, in case the client never tells us it stopped.
COMPOSING_TTL_SECONDS = 15
MAX_VIEWERS_RETURNED = 20

PresenceActivity = Literal["viewing", "composing"]
PRESENCE_ACTIVITIES: tuple[str, ...] = get_args(PresenceActivity)

_USER_ID_FIELD = "u"
_ACTIVITY_FIELD = "a"


@dataclasses.dataclass(frozen=True, kw_only=True)
class PresenceEntry:
    client_id: str
    user_id: int
    activity: PresenceActivity
    last_seen_at: datetime


def heartbeat(
    team_id: int,
    scope: str,
    item_id: str,
    *,
    client_id: str,
    user_id: int,
    activity: PresenceActivity = "viewing",
    now: datetime | None = None,
) -> list[PresenceEntry]:
    """Record this client and return everyone currently here, so a caller needs one round trip."""
    now = now or datetime.now(UTC)
    index_key, meta_key = _keys(team_id, scope, item_id)
    # No PII in Redis — the API hydrates names and emails from Postgres per request.
    payload = {_USER_ID_FIELD: user_id, _ACTIVITY_FIELD: activity}

    try:
        client = redis_module.get_client()
        pipeline = client.pipeline(transaction=False)
        pipeline.zadd(index_key, {client_id: _to_ms(now)})
        pipeline.hset(meta_key, client_id, json.dumps(payload, separators=(",", ":")))
        pipeline.expire(index_key, PRESENCE_KEY_TTL_SECONDS)
        pipeline.expire(meta_key, PRESENCE_KEY_TTL_SECONDS)
        pipeline.zrange(index_key, 0, -1, withscores=True)
        pipeline.hgetall(meta_key)
        results = pipeline.execute()
        scored, raw_meta = results[-2], results[-1]
    except redis_exceptions.RedisError as err:
        logger.warning("presence_heartbeat_error", scope=scope, item_id=item_id, error=str(err))
        return []

    _collect_garbage(index_key, meta_key, scored=scored, raw_meta=raw_meta, now=now, scope=scope)
    return _parse(scored, raw_meta, now=now)


def get_viewers(
    team_id: int,
    scope: str,
    item_id: str,
    *,
    now: datetime | None = None,
) -> list[PresenceEntry]:
    """Read-only view of who is here. One round trip; stale entries are filtered, not deleted."""
    now = now or datetime.now(UTC)
    index_key, meta_key = _keys(team_id, scope, item_id)

    try:
        client = redis_module.get_client()
        pipeline = client.pipeline(transaction=False)
        pipeline.zrange(index_key, 0, -1, withscores=True)
        pipeline.hgetall(meta_key)
        scored, raw_meta = pipeline.execute()
    except redis_exceptions.RedisError as err:
        logger.warning("presence_get_viewers_error", scope=scope, item_id=item_id, error=str(err))
        return []

    return _parse(scored, raw_meta, now=now)


def leave(team_id: int, scope: str, item_id: str, *, client_id: str) -> None:
    """Best-effort removal on tab close, so the avatar goes rather than waiting out the TTL."""
    index_key, meta_key = _keys(team_id, scope, item_id)

    try:
        client = redis_module.get_client()
        pipeline = client.pipeline(transaction=False)
        pipeline.zrem(index_key, client_id)
        pipeline.hdel(meta_key, client_id)
        pipeline.execute()
    except redis_exceptions.RedisError as err:
        logger.warning("presence_leave_error", scope=scope, item_id=item_id, error=str(err))


def _keys(team_id: int, scope: str, item_id: str) -> tuple[str, str]:
    return (
        PRESENCE_INDEX_KEY_PATTERN.format(team_id=team_id, scope=scope, item_id=item_id),
        PRESENCE_META_KEY_PATTERN.format(team_id=team_id, scope=scope, item_id=item_id),
    )


def _to_ms(moment: datetime) -> int:
    return int(moment.timestamp() * 1000)


def _decode(value: bytes | str) -> str:
    return value.decode() if isinstance(value, bytes) else value


def _parse(
    scored: list[tuple[bytes | str, float]],
    raw_meta: dict[bytes | str, bytes | str],
    *,
    now: datetime,
) -> list[PresenceEntry]:
    cutoff_ms = _to_ms(now - timedelta(seconds=PRESENCE_TTL_SECONDS))
    composing_cutoff = now - timedelta(seconds=COMPOSING_TTL_SECONDS)
    meta = {_decode(key): _decode(value) for key, value in raw_meta.items()}

    entries: list[PresenceEntry] = []
    for member, score in scored:
        if score <= cutoff_ms:
            continue
        client_id = _decode(member)
        raw_payload = meta.get(client_id)
        if raw_payload is None:
            continue
        try:
            payload = json.loads(raw_payload)
            user_id = int(payload[_USER_ID_FIELD])
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            continue

        activity = payload.get(_ACTIVITY_FIELD)
        if activity not in PRESENCE_ACTIVITIES:
            activity = "viewing"
        last_seen_at = datetime.fromtimestamp(score / 1000, tz=UTC)
        if activity == "composing" and last_seen_at < composing_cutoff:
            activity = "viewing"

        entries.append(
            PresenceEntry(
                client_id=client_id,
                user_id=user_id,
                activity=cast(PresenceActivity, activity),
                last_seen_at=last_seen_at,
            )
        )

    entries.sort(key=lambda entry: entry.last_seen_at, reverse=True)
    return entries[:MAX_VIEWERS_RETURNED]


def _collect_garbage(
    index_key: str,
    meta_key: str,
    *,
    scored: list[tuple[bytes | str, float]],
    raw_meta: dict[bytes | str, bytes | str],
    now: datetime,
    scope: str,
) -> None:
    """Drop expired clients and orphaned payloads. Only the write path pays for this, so reads stay
    one round trip. Deliberately keyed on the TTL cutoff rather than on what a read returned, so
    `MAX_VIEWERS_RETURNED` truncation can never evict a live viewer."""
    cutoff_ms = _to_ms(now - timedelta(seconds=PRESENCE_TTL_SECONDS))
    live = {_decode(member) for member, score in scored if score > cutoff_ms}
    stale_members = [_decode(member) for member, score in scored if score <= cutoff_ms]
    stale_fields = [_decode(field) for field in raw_meta if _decode(field) not in live]
    if not stale_members and not stale_fields:
        return

    try:
        client = redis_module.get_client()
        pipeline = client.pipeline(transaction=False)
        if stale_members:
            pipeline.zrem(index_key, *stale_members)
        if stale_fields:
            pipeline.hdel(meta_key, *stale_fields)
        pipeline.execute()
    except redis_exceptions.RedisError as err:
        logger.warning("presence_gc_error", scope=scope, error=str(err))
