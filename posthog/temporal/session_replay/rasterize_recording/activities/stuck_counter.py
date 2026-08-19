from dataclasses import dataclass
from datetime import timedelta

import structlog
from temporalio import activity

from posthog.redis import get_async_client, get_client

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


# A run only bumps the counter after its final scheduled attempt, so 2 means the session has burned
# through two whole retry envelopes inside the TTL window without a success.
STUCK_SESSION_THRESHOLD = 2


def read_stuck_session_ids(
    team_id: int,
    session_ids: list[str],
    threshold: int = STUCK_SESSION_THRESHOLD,
) -> set[str]:
    """Which of `session_ids` are quarantined. Sync because every caller is a synchronous activity."""
    if not session_ids:
        return set()
    values = get_client().mget([_stuck_key(team_id, sid) for sid in session_ids])
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
