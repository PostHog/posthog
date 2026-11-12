import hashlib
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.core.cache import cache

from rest_framework import serializers

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.workload import Workload
from posthog.dataclasses import frozen
from posthog.models import Team

QUERY_USAGE_WINDOW_DAYS = 30
QUERY_USAGE_CACHE_TTL_SECONDS = 24 * 60 * 60
# A usage row in the days just before the earlier window starts proves that tracking was on for all of it.
# Without that proof, a team that turned tracking on mid-window would get a comparison against a partial count.
COVERAGE_LOOKBACK_DAYS = 7


@frozen
class QueryUsageWindows:
    current_start: datetime
    previous_start: datetime
    previous_end: datetime
    coverage_start: datetime
    days: tuple[date, ...]


@frozen
class QueryUsageDay:
    date: date
    count: int


@frozen
class QueryUsage:
    total: int
    previous_total: int | None
    daily: tuple[QueryUsageDay, ...]


def query_usage_windows(now: datetime, timezone: ZoneInfo) -> QueryUsageWindows:
    """The current window is the last 30 days in the team's timezone, with today still in progress.

    The previous window ends at the same time of day 30 days earlier, so both windows cover the same length of time
    and the comparison does not shrink while today fills up.
    """
    local_now = now.astimezone(timezone)
    first_day = local_now.date() - timedelta(days=QUERY_USAGE_WINDOW_DAYS - 1)
    previous_start = datetime.combine(first_day - timedelta(days=QUERY_USAGE_WINDOW_DAYS), time.min, tzinfo=timezone)
    return QueryUsageWindows(
        current_start=datetime.combine(first_day, time.min, tzinfo=timezone),
        previous_start=previous_start,
        previous_end=local_now - timedelta(days=QUERY_USAGE_WINDOW_DAYS),
        coverage_start=previous_start - timedelta(days=COVERAGE_LOOKBACK_DAYS),
        days=tuple(first_day + timedelta(days=offset) for offset in range(QUERY_USAGE_WINDOW_DAYS)),
    )


def summarize_query_usage(
    daily_counts: list[tuple[date, int]], windows: QueryUsageWindows, previous_covered: bool
) -> QueryUsage:
    """Sums per-day counts into the two windows. Days without a count get zero."""
    current: dict[date, int] = {}
    previous_total = 0
    for day, count in daily_counts:
        if day >= windows.days[0]:
            current[day] = current.get(day, 0) + count
        else:
            previous_total += count
    daily = tuple(QueryUsageDay(date=day, count=current.get(day, 0)) for day in windows.days)
    return QueryUsage(
        total=sum(day.count for day in daily),
        previous_total=previous_total if previous_covered else None,
        daily=daily,
    )


def fetch_query_usage(team: Team, app_source: str, instance_ids: list[str]) -> dict[str, QueryUsage]:
    """Query usage for each app_metrics2 instance id, cached for a day per instance id."""
    cache_keys = {instance_id: _cache_key(team.pk, app_source, instance_id) for instance_id in set(instance_ids)}
    cached = cache.get_many(list(cache_keys.values()))
    usage: dict[str, QueryUsage] = {}
    missing: list[str] = []
    for instance_id, cache_key in cache_keys.items():
        value = cached.get(cache_key)
        if isinstance(value, QueryUsage):
            usage[instance_id] = value
        else:
            missing.append(instance_id)

    if missing:
        windows = query_usage_windows(datetime.now(UTC), team.timezone_info)
        fresh = _fetch_uncached_query_usage(team, app_source, missing, windows)
        cache.set_many(
            {cache_keys[instance_id]: fresh[instance_id] for instance_id in missing},
            timeout=QUERY_USAGE_CACHE_TTL_SECONDS,
        )
        usage.update(fresh)
    return usage


def _cache_key(team_id: int, app_source: str, instance_id: str) -> str:
    # Definition names can contain characters that are invalid in cache keys, so hash the instance id.
    digest = hashlib.sha256(instance_id.encode()).hexdigest()[:32]
    return f"query_usage:v1:{team_id}:{app_source}:{digest}"


def _clickhouse_datetime(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S.%f")


def _fetch_uncached_query_usage(
    team: Team, app_source: str, instance_ids: list[str], windows: QueryUsageWindows
) -> dict[str, QueryUsage]:
    rows = sync_execute(
        """
        SELECT instance_id, toDate(timestamp, %(timezone)s) AS day, sum(count)
        FROM app_metrics2
        WHERE team_id = %(team_id)s
          AND app_source = %(app_source)s
          AND metric_name = 'viewed'
          AND instance_id IN %(instance_ids)s
          AND timestamp >= toDateTime64(%(previous_start)s, 6, 'UTC')
          AND (
            timestamp < toDateTime64(%(previous_end)s, 6, 'UTC')
            OR timestamp >= toDateTime64(%(current_start)s, 6, 'UTC')
          )
        GROUP BY instance_id, day
        """,
        {
            "team_id": team.pk,
            "app_source": app_source,
            "instance_ids": instance_ids,
            "timezone": str(windows.current_start.tzinfo),
            "previous_start": _clickhouse_datetime(windows.previous_start),
            "previous_end": _clickhouse_datetime(windows.previous_end),
            "current_start": _clickhouse_datetime(windows.current_start),
        },
        team_id=team.pk,
        workload=Workload.ONLINE,
    )
    daily_counts: dict[str, list[tuple[date, int]]] = {instance_id: [] for instance_id in instance_ids}
    for instance_id, day, count in rows or []:
        if instance_id in daily_counts:
            daily_counts[instance_id].append((day, int(count)))

    previous_covered = _previous_window_covered(team, app_source, windows)
    return {
        instance_id: summarize_query_usage(counts, windows, previous_covered)
        for instance_id, counts in daily_counts.items()
    }


def _previous_window_covered(team: Team, app_source: str, windows: QueryUsageWindows) -> bool:
    rows = sync_execute(
        """
        SELECT 1
        FROM app_metrics2
        WHERE team_id = %(team_id)s
          AND app_source = %(app_source)s
          AND metric_name = 'viewed'
          AND timestamp >= toDateTime64(%(coverage_start)s, 6, 'UTC')
          AND timestamp < toDateTime64(%(previous_start)s, 6, 'UTC')
        LIMIT 1
        """,
        {
            "team_id": team.pk,
            "app_source": app_source,
            "coverage_start": _clickhouse_datetime(windows.coverage_start),
            "previous_start": _clickhouse_datetime(windows.previous_start),
        },
        team_id=team.pk,
        workload=Workload.ONLINE,
    )
    return bool(rows)


class QueryUsageDaySerializer(serializers.Serializer):
    date = serializers.DateField(help_text="Day in the project's timezone.")
    count = serializers.IntegerField(help_text="Query executions on this day.")


# Reads a `usage` attribute or key that holds a `QueryUsage`. A docstring here would become the OpenAPI
# description of every subclass, so this note stays a comment.
class QueryUsageSerializer(serializers.Serializer):
    query_usage_30_day = serializers.IntegerField(
        source="usage.total",
        help_text=(
            "Query executions in the last 30 days that referenced this definition, including cached insight views. "
            "The window starts at midnight 29 days ago in the project's timezone and includes today."
        ),
    )
    query_usage_previous_30_day = serializers.IntegerField(
        source="usage.previous_total",
        allow_null=True,
        help_text=(
            "Query executions in the 30 days before that window, up to the same time of day as now, "
            "so both windows cover the same length of time. Null when usage tracking did not cover that whole period."
        ),
    )
    query_usage_daily = QueryUsageDaySerializer(
        source="usage.daily",
        many=True,
        help_text="Query executions per day for the last 30 days, oldest first. The last day is today and is still in progress.",
    )
