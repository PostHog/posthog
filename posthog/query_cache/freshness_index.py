from datetime import UTC, datetime
from typing import Optional

from posthog import redis

_REDIS_KEY_PREFIX = "cache_timestamps"
_LAST_REFRESH_KEY_PREFIX = "cache_last_refresh"


def _redis_key(team_id: int) -> str:
    return f"{_REDIS_KEY_PREFIX}:{team_id}"


def _last_refresh_key(team_id: int) -> str:
    return f"{_LAST_REFRESH_KEY_PREFIX}:{team_id}"


def insight_identifier(insight_id: int, dashboard_id: Optional[int]) -> str:
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


def stale_among(*, team_id: int, identifiers: set[str]) -> list[str]:
    """The given identifiers that are stale, ordered like `get_stale_insights`: least stale first."""
    if not identifiers:
        return []
    ordered = sorted(identifiers)
    scores = redis.get_client().zmscore(_redis_key(team_id), ordered)
    now = datetime.now(UTC).timestamp()
    stale = [(score, identifier) for identifier, score in zip(ordered, scores) if score is not None and score <= now]
    return [identifier for _, identifier in sorted(stale, reverse=True)]


def last_refreshes(*, team_id: int, identifiers: list[str]) -> dict[str, Optional[datetime]]:
    """When each identifier's cached result was last computed, or None when no computation was recorded."""
    if not identifiers:
        return {}
    scores = redis.get_client().zmscore(_last_refresh_key(team_id), identifiers)
    return {
        identifier: datetime.fromtimestamp(score, UTC) if score is not None else None
        for identifier, score in zip(identifiers, scores)
    }


def clean_up_stale_insights(*, team_id: int, threshold: datetime) -> None:
    """Remove all stale insights that are older than the given timestamp."""
    pipeline = redis.get_client().pipeline(transaction=False)
    pipeline.zremrangebyscore(_redis_key(team_id), "-inf", threshold.timestamp())
    pipeline.zremrangebyscore(_last_refresh_key(team_id), "-inf", threshold.timestamp())
    pipeline.execute()


def update_target_age(
    *,
    team_id: int,
    insight_id: Optional[int],
    dashboard_id: Optional[int],
    target_age: datetime,
    last_refresh: Optional[datetime] = None,
) -> None:
    """Update the target age for insight freshness tracking using Redis sorted sets."""
    if not insight_id:
        return
    identifier = insight_identifier(insight_id, dashboard_id)
    pipeline = redis.get_client().pipeline(transaction=False)
    pipeline.zadd(_redis_key(team_id), {identifier: target_age.timestamp()})
    if last_refresh is not None:
        pipeline.zadd(_last_refresh_key(team_id), {identifier: last_refresh.timestamp()})
    pipeline.execute()


def remove_last_refresh(*, team_id: int, insight_id: Optional[int], dashboard_id: Optional[int]) -> None:
    """Remove insight from freshness tracking using Redis sorted sets."""
    if not insight_id:
        return
    identifier = insight_identifier(insight_id, dashboard_id)
    pipeline = redis.get_client().pipeline(transaction=False)
    pipeline.zrem(_redis_key(team_id), identifier)
    pipeline.zrem(_last_refresh_key(team_id), identifier)
    pipeline.execute()
