from dataclasses import dataclass
from datetime import timedelta

import structlog
import redis.exceptions
from redis.asyncio import Redis as AsyncRedis
from temporalio import activity

from posthog.redis import get_async_client

logger = structlog.get_logger(__name__)

_STUCK_KEY_PREFIX = "replay:rasterize:stuck"
# Each new failure refreshes the TTL, so the window slides on the most recent failure.
STUCK_RASTERIZE_LOOKBACK = timedelta(hours=2)
_STUCK_TTL_SECONDS = int(STUCK_RASTERIZE_LOOKBACK.total_seconds())

# Transient Redis connectivity blips (DNS/connect timeouts, dropped connections). The stuck
# counter is best-effort bookkeeping, so we swallow these rather than let the activity
# interceptor report a deliberately-tolerated failure as a new error-tracking issue.
_TRANSIENT_REDIS_ERRORS = (redis.exceptions.ConnectionError, redis.exceptions.TimeoutError)


def _stuck_key(team_id: int, session_id: str) -> str:
    return f"{_STUCK_KEY_PREFIX}:{team_id}:{session_id}"


@dataclass
class BumpStuckCounterInput:
    team_id: int
    session_id: str


@activity.defn
async def bump_stuck_counter_activity(inputs: BumpStuckCounterInput) -> None:
    redis_client = get_async_client()
    key = _stuck_key(inputs.team_id, inputs.session_id)
    try:
        async with redis_client.pipeline(transaction=False) as pipe:
            pipe.incr(key)
            pipe.expire(key, _STUCK_TTL_SECONDS)
            await pipe.execute()
    except _TRANSIENT_REDIS_ERRORS as exc:
        logger.warning(
            "rasterize.stuck_counter_bump_skipped_redis_unavailable",
            team_id=inputs.team_id,
            session_id=inputs.session_id,
            error=str(exc),
        )
        return
    logger.info(
        "rasterize.stuck_counter_bumped",
        team_id=inputs.team_id,
        session_id=inputs.session_id,
    )


@activity.defn
async def clear_stuck_counter_activity(inputs: BumpStuckCounterInput) -> None:
    """Reset the counter on success; without this, sporadic failures accumulate within the TTL window."""
    redis_client = get_async_client()
    key = _stuck_key(inputs.team_id, inputs.session_id)
    try:
        await redis_client.delete(key)
    except _TRANSIENT_REDIS_ERRORS as exc:
        logger.warning(
            "rasterize.stuck_counter_clear_skipped_redis_unavailable",
            team_id=inputs.team_id,
            session_id=inputs.session_id,
            error=str(exc),
        )


async def read_stuck_session_ids(
    redis_client: AsyncRedis,
    team_id: int,
    session_ids: list[str],
    threshold: int,
) -> set[str]:
    if not session_ids:
        return set()
    keys = [_stuck_key(team_id, sid) for sid in session_ids]
    values = await redis_client.mget(keys)
    stuck: set[str] = set()
    for sid, val in zip(session_ids, values):
        if val is None:
            continue
        try:
            count = int(val)
        except (TypeError, ValueError):
            continue
        if count >= threshold:
            stuck.add(sid)
    return stuck
