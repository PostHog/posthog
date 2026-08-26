"""
Ephemeral "who has this ticket open" presence for the support queue.

Each ticket gets a Redis sorted set of user ids scored by their last heartbeat. Readers
only return members newer than the TTL, so a missed write self-heals on the next
heartbeat and a closed tab fades out on its own. Redis failures are logged and
swallowed: presence is a hint, never a source of truth.
"""

import time
from collections.abc import Sequence

import structlog
import redis.exceptions as redis_exceptions

from posthog.redis import get_client

logger = structlog.get_logger(__name__)

PRESENCE_TTL_SECONDS = 30


def _presence_key(team_id: int, ticket_id: str) -> str:
    return f"conversations:ticket_presence:{team_id}:{ticket_id}"


def record_ticket_presence(team_id: int, ticket_id: str, user_id: int) -> None:
    now = time.time()
    key = _presence_key(team_id, ticket_id)
    try:
        pipeline = get_client().pipeline(transaction=False)
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
        pipeline = get_client().pipeline(transaction=False)
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
