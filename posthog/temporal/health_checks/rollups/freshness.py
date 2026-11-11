from __future__ import annotations

import datetime as dt
from collections.abc import Collection
from typing import Any

from django.core.cache import cache
from django.db import connections, models, router

import structlog

from posthog.dataclasses import frozen

logger = structlog.get_logger(__name__)

PUBLISHED_DAYS_CACHE_SECONDS = 5 * 60
MAX_LATEST_DAY_AGE_DAYS = 2
MAX_PUBLISHED_DAYS_LISTED = 64


@frozen
class RollupWindow:
    start: dt.date
    end: dt.date

    def __post_init__(self) -> None:
        if self.start > self.end:
            raise ValueError(f"RollupWindow start {self.start} is after end {self.end}")

    @property
    def live_since(self) -> dt.datetime:
        """The UTC instant after the window, from which live queries cover the gap to now."""
        return dt.datetime.combine(self.end + dt.timedelta(days=1), dt.time.min, tzinfo=dt.UTC)


def window_rows(model: type[models.Model], team_ids: Collection[int], window: RollupWindow) -> models.QuerySet[Any]:
    """The rollup rows of these environments inside the window. Name the model in READ_REPLICA_OPT_IN to read the replica."""
    return model.objects.unscoped().filter(  # type: ignore[attr-defined]
        team_id__in=team_ids, day__range=(window.start, window.end)
    )


def _published_days_cache_key(table: str) -> str:
    return f"daily_rollup:published_days:{table}"


def _query_published_days(table: str, using: str) -> list[dt.date]:
    query = f"""
        WITH RECURSIVE published(day) AS (
            (SELECT day FROM {table} ORDER BY day DESC LIMIT 1)
            UNION ALL
            SELECT (SELECT t.day FROM {table} t WHERE t.day < published.day ORDER BY t.day DESC LIMIT 1)
            FROM published
            WHERE published.day IS NOT NULL
        )
        SELECT day FROM published WHERE day IS NOT NULL LIMIT %s
    """
    with connections[using].cursor() as cursor:
        cursor.execute(query, [MAX_PUBLISHED_DAYS_LISTED])
        return [row[0] for row in cursor.fetchall()]


def published_days(model: type[models.Model]) -> list[dt.date]:
    """Published days of a rollup table, newest first, cached for a few minutes."""
    table = model._meta.db_table
    cache_key = _published_days_cache_key(table)
    cached = cache.get(cache_key)
    if cached is not None:
        return [dt.date.fromisoformat(day) for day in cached]
    days = _query_published_days(table, router.db_for_read(model))
    cache.set(cache_key, [day.isoformat() for day in days], PUBLISHED_DAYS_CACHE_SECONDS)
    return days


def invalidate_published_days(model: type[models.Model]) -> None:
    cache.delete(_published_days_cache_key(model._meta.db_table))


def window_from_published_days(
    published: list[dt.date], days: int, *, today: dt.date, table: str = ""
) -> RollupWindow | None:
    """The `days`-day window ending at the newest published day, or None when readers must not use it.

    None when nothing is published, when the newest day is too old, or when any day of the window
    is missing. A reader that sums a window with a gap would undercount, and a check would read
    the undercount as missing events.
    """
    if days <= 0:
        raise ValueError(f"days must be > 0, got {days}")
    if not published:
        logger.warning("daily rollup has no published days", table=table)
        return None
    latest = max(published)
    if latest < today - dt.timedelta(days=MAX_LATEST_DAY_AGE_DAYS):
        logger.warning("daily rollup is stale", table=table, latest_day=latest.isoformat(), today=today.isoformat())
        return None
    window = RollupWindow(start=latest - dt.timedelta(days=days - 1), end=latest)
    published_set = set(published)
    missing = [
        day for day in (window.start + dt.timedelta(days=offset) for offset in range(days)) if day not in published_set
    ]
    if missing:
        logger.warning(
            "daily rollup window has missing days",
            table=table,
            window_days=days,
            missing_days=[day.isoformat() for day in missing[:10]],
            missing_count=len(missing),
        )
        return None
    return window


def rollup_window(model: type[models.Model], days: int) -> RollupWindow | None:
    return window_from_published_days(
        published_days(model), days, today=dt.datetime.now(dt.UTC).date(), table=model._meta.db_table
    )
