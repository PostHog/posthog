"""
Ephemeral "who has this ticket open" presence for the support queue.

Each ticket gets a Redis sorted set of user ids scored by their last heartbeat. Readers
only return members newer than the TTL, so a missed write self-heals on the next
heartbeat and a closed tab fades out on its own. Redis failures are logged and
swallowed: presence is a hint, never a source of truth.
"""

import time
from collections.abc import Sequence
from functools import lru_cache

from django.conf import settings

import redis
import structlog
import redis.exceptions as redis_exceptions

from posthog.redis import get_client

logger = structlog.get_logger(__name__)

PRESENCE_TTL_SECONDS = 30

# The shared Redis client uses REDIS_SOCKET_TIMEOUT_SECONDS (20s by default), so a reachable but
# slow Redis could pin a request worker for the full timeout on each call. Presence is a hint that
# may be lost, so it fails fast instead, the way the DB circuit breaker caps its own Redis path.
_PRESENCE_REDIS_OP_TIMEOUT_SECONDS = 0.1


@lru_cache(maxsize=1)
def _presence_redis() -> redis.Redis:
    """Dedicated, tightly-timed Redis client for the best-effort presence path."""
    if settings.TEST or not settings.REDIS_URL:
        return get_client()
    return redis.from_url(
        settings.REDIS_URL,
        db=0,
        socket_timeout=_PRESENCE_REDIS_OP_TIMEOUT_SECONDS,
        socket_connect_timeout=_PRESENCE_REDIS_OP_TIMEOUT_SECONDS,
    )


def _presence_key(team_id: int, ticket_id: str) -> str:
    return f"conversations:ticket_presence:{team_id}:{ticket_id}"


def record_ticket_presence(team_id: int, ticket_id: str, user_id: int) -> None:
    now = time.time()
    key = _presence_key(team_id, ticket_id)
    try:
        pipeline = _presence_redis().pipeline(transaction=False)
        pipeline.zadd(key, {str(user_id): now})
        pipeline.zremrangebyscore(key, "-inf", now - PRESENCE_TTL_SECONDS)
        pipeline.expire(key, PRESENCE_TTL_SECONDS)
        pipeline.execute()
    except redis_exceptions.RedisError as err:
        logger.warning("ticket_presence_record_error", team_id=team_id, ticket_id=ticket_id, error=str(err))


def get_ticket_viewers(team_id: int, ticket_ids: Sequence[str]) -> dict[str, list[int]]:
    """Active viewer ids per ticket, most recent first. Tickets with no viewers are omitted."""
    if not ticket_ids:
        return {}
    cutoff = time.time() - PRESENCE_TTL_SECONDS
    try:
        pipeline = _presence_redis().pipeline(transaction=False)
        for ticket_id in ticket_ids:
            pipeline.zrevrangebyscore(_presence_key(team_id, ticket_id), "+inf", cutoff)
        results = pipeline.execute()
    except redis_exceptions.RedisError as err:
        logger.warning("ticket_presence_read_error", team_id=team_id, error=str(err))
        return {}

    viewers: dict[str, list[int]] = {}
    for ticket_id, members in zip(ticket_ids, results):
        if members:
            viewers[ticket_id] = [int(member) for member in members]
    return viewers
