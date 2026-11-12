from datetime import UTC, datetime, timedelta
from typing import Optional

from posthog import redis
from posthog.query_cache.freshness_index import insight_identifier

_REDIS_KEY_PREFIX = "cache_reads"
HISTORY_DAYS = 7
_TTL = timedelta(days=HISTORY_DAYS + 1)


def _redis_key(team_id: int, hour: datetime) -> str:
    return f"{_REDIS_KEY_PREFIX}:{team_id}:{hour.astimezone(UTC):%Y%m%d%H}"


def record_read(*, team_id: int, insight_id: Optional[int], dashboard_id: Optional[int], at: datetime) -> None:
    if not insight_id:
        return
    key = _redis_key(team_id, at)
    pipeline = redis.get_client().pipeline(transaction=False)
    pipeline.sadd(key, insight_identifier(insight_id, dashboard_id))
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
