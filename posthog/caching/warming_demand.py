from datetime import UTC, datetime, timedelta

import structlog

from posthog import redis

logger = structlog.get_logger(__name__)

VIEW_RETENTION = timedelta(days=365)


def _key(team_id: int) -> str:
    return f"cache_warming_dashboard_views:{team_id}"


def record_dashboard_view_for_warming(*, team_id: int, dashboard_id: int) -> None:
    """Remember that a person opened the dashboard, in the app or through a shared or embedded link.

    `Dashboard.last_accessed_at` cannot carry this: API reads and export renders also set it, and
    the dashboard list and the recently accessed surfaces sort by it.
    """
    try:
        redis.get_client().zadd(_key(team_id), {str(dashboard_id): datetime.now(UTC).timestamp()})
    except Exception:
        logger.exception("cache_warming_dashboard_view_write_failed", team_id=team_id, dashboard_id=dashboard_id)


def dashboard_views_since(*, team_id: int, since: datetime) -> dict[int, datetime]:
    client = redis.get_client()
    client.zremrangebyscore(_key(team_id), "-inf", (datetime.now(UTC) - VIEW_RETENTION).timestamp())
    views = client.zrangebyscore(_key(team_id), since.timestamp(), "+inf", withscores=True)
    return {int(dashboard_id): datetime.fromtimestamp(viewed_at, UTC) for dashboard_id, viewed_at in views}
