from datetime import UTC, datetime
from typing import Optional

from posthog import redis

_REDIS_KEY_PREFIX = "cache_timestamps"


def _redis_key(team_id: int) -> str:
    return f"{_REDIS_KEY_PREFIX}:{team_id}"


def _identifier(insight_id: int, dashboard_id: Optional[int]) -> str:
    return f"{insight_id}:{dashboard_id or ''}"


def get_stale_insights(*, team_id: int, limit: Optional[int] = None) -> list[str]:
    """
    Use redis sorted set to get stale insights. We sort by the timestamp and get the insights that are
    stale compared to the current time.

    We start with the least stale insights: Because we want to keep in mind
    that we might not have enough time to refresh all insights. This way, and only if we don't manage to refresh
    all insights, we try our best to keep a number of insights fully up-to-date, instead of only achieving to
    refresh the most stale ones while failing to refresh the rest. Should an insight be refreshed by user or other
    means it will be the freshest anyway again.

    It is accepted that we store all combinations of insight + dashboard, even if the dashboard might not have
    additional filters (which makes this dashboard insight the same as the single one). This is easily mitigated by
    the fact we should have the very same cache key for these and we calculate the insights in sequence. Thus, the
    first calculation to refresh it will refresh all of them.
    """
    current_time = datetime.now(UTC)
    redis_key = _redis_key(team_id)
    # get least stale insights first
    if limit is not None:
        insights = redis.get_client().zrevrangebyscore(
            name=redis_key, max=current_time.timestamp(), min="-inf", start=0, num=limit
        )
    else:
        insights = redis.get_client().zrevrangebyscore(name=redis_key, max=current_time.timestamp(), min="-inf")
    return [insight.decode("utf-8") for insight in insights]


def clean_up_stale_insights(*, team_id: int, threshold: datetime) -> None:
    """Remove all stale insights that are older than the given timestamp."""
    redis.get_client().zremrangebyscore(_redis_key(team_id), "-inf", threshold.timestamp())


def update_target_age(
    *, team_id: int, insight_id: Optional[int], dashboard_id: Optional[int], target_age: datetime
) -> None:
    """Update the target age for insight freshness tracking using Redis sorted sets."""
    if not insight_id:
        return
    redis.get_client().zadd(_redis_key(team_id), {_identifier(insight_id, dashboard_id): target_age.timestamp()})


def remove_last_refresh(*, team_id: int, insight_id: Optional[int], dashboard_id: Optional[int]) -> None:
    """Remove insight from freshness tracking using Redis sorted sets."""
    if not insight_id:
        return
    redis.get_client().zrem(_redis_key(team_id), _identifier(insight_id, dashboard_id))
