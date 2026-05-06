from dataclasses import dataclass
from datetime import timedelta

import structlog
from redis.asyncio import Redis as AsyncRedis
from temporalio import activity

from posthog.redis import get_async_client

logger = structlog.get_logger(__name__)

_STUCK_KEY_PREFIX = "replay:rasterize:stuck"
# Each new failure refreshes the TTL, so the window slides on the most recent failure.
STUCK_RASTERIZE_LOOKBACK = timedelta(hours=2)
_STUCK_TTL_SECONDS = int(STUCK_RASTERIZE_LOOKBACK.total_seconds())


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
    async with redis_client.pipeline(transaction=False) as pipe:
        pipe.incr(key)
        pipe.expire(key, _STUCK_TTL_SECONDS)
        await pipe.execute()
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
    await redis_client.delete(key)


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
