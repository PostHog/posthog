from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime, timedelta
from typing import Optional

import structlog

from posthog import redis
from posthog.query_cache.freshness_index import insight_identifier

logger = structlog.get_logger(__name__)

_REDIS_KEY_PREFIX = "cache_reads"
HISTORY_DAYS = 7
_TTL = timedelta(days=HISTORY_DAYS + 1)
_RECORD_TIMEOUT_SECONDS = 0.25


def _redis_key(team_id: int, hour: datetime) -> str:
    return f"{_REDIS_KEY_PREFIX}:{team_id}:{hour.astimezone(UTC):%Y%m%d%H}"


# Reads recorded inside `batched_reads`, by Redis key. None outside it, so a read is written at once.
_pending_reads: ContextVar[dict[str, set[str]] | None] = ContextVar("query_cache_pending_reads", default=None)


@contextmanager
def batched_reads() -> Iterator[None]:
    """Write the reads recorded inside the block in one Redis round trip when it ends.

    A dashboard records a read for every tile it serves, which otherwise costs a round trip per tile."""
    pending: dict[str, set[str]] = {}
    token = _pending_reads.set(pending)
    try:
        yield
    finally:
        _pending_reads.reset(token)
        try:
            _write_reads(pending)
        except Exception:
            # Same as an unbatched read: losing the history must not fail the request that served the results.
            logger.exception("query_cache_record_reads_failed", keys=len(pending))


def record_read(*, team_id: int, insight_id: Optional[int], dashboard_id: Optional[int], at: datetime) -> None:
    if not insight_id:
        return
    key = _redis_key(team_id, at)
    identifier = insight_identifier(insight_id, dashboard_id)
    pending = _pending_reads.get()
    if pending is not None:
        pending.setdefault(key, set()).add(identifier)
        return
    _write_reads({key: {identifier}})


def _write_reads(reads: dict[str, set[str]]) -> None:
    if not reads:
        return
    client = redis.get_client(socket_timeout=_RECORD_TIMEOUT_SECONDS, socket_connect_timeout=_RECORD_TIMEOUT_SECONDS)
    pipeline = client.pipeline(transaction=False)
    for key, identifiers in reads.items():
        pipeline.sadd(key, *sorted(identifiers))
        pipeline.expire(key, _TTL)
    pipeline.execute()


def days_read_at_this_time(*, team_id: int, identifiers: list[str], now: datetime) -> dict[str, int]:
    if not identifiers:
        return {}
    pipeline = redis.get_client().pipeline(transaction=False)
    for days_ago in range(1, HISTORY_DAYS + 1):
        for hours_ahead in (0, 1):
            hour = now - timedelta(days=days_ago) + timedelta(hours=hours_ahead)
            pipeline.smismember(_redis_key(team_id, hour), identifiers)
    membership = pipeline.execute()
    days = dict.fromkeys(identifiers, 0)
    for this_hour, next_hour in zip(membership[::2], membership[1::2]):
        for identifier, read_this_hour, read_next_hour in zip(identifiers, this_hour, next_hour):
            if read_this_hour or read_next_hour:
                days[identifier] += 1
    return days


def read_since(*, team_id: int, since: datetime, now: datetime) -> set[str]:
    """Identifiers read at least once in the hours from `since` to `now`, both hours included."""
    first_hour = since.astimezone(UTC).replace(minute=0, second=0, microsecond=0)
    hours = int((now - first_hour) // timedelta(hours=1)) + 1
    keys = [_redis_key(team_id, first_hour + timedelta(hours=hour)) for hour in range(hours)]
    members = redis.get_client().sunion(keys)
    return {member.decode("utf-8") if isinstance(member, bytes) else str(member) for member in members}
