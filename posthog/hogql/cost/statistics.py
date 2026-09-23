"""Per-team statistics for the HogQL cost planner.

The estimator asks one question of many sources: how big is this thing for this team? The sources differ
(a ClickHouse rollup, a warehouse Delta log, a Postgres definition table) and most of them can be missing.
This module gives them one shape. A provider returns ``None`` for any fact it cannot supply, and the
estimator decides what to do without it, so a missing statistic never fails a query.

``ClickHouseStatisticsProvider`` reads the rollups the ingestion pipeline already maintains.
``FixedStatisticsProvider`` returns whatever a test hands it.
"""

from collections.abc import Mapping
from datetime import date, timedelta
from typing import Protocol

from django.conf import settings
from django.core.cache import cache

import structlog

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.property_values import DISTRIBUTED_TABLE_NAME as PROPERTY_VALUES_TABLE
from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.clickhouse.workload import Workload
from posthog.dataclasses import frozen
from posthog.models.group.sql import GROUPS_TABLE
from posthog.models.person.sql import PERSONS_TABLE
from posthog.models.usage_report_events_preagg.sql import (
    USAGE_REPORT_EVENTS_PREAGG_TABLE,
    USAGE_REPORT_EVENTS_PREAGG_TTL_DAYS,
)

logger = structlog.get_logger(__name__)

# The rollup drops parts past its TTL, so a window this long is the most it can answer. Today is excluded
# because it is still filling, and a team that stopped sending has fewer days than the window, so callers
# scale by ``EventVolume.days`` rather than dividing by the window they asked for.
EVENT_VOLUME_WINDOW_DAYS = USAGE_REPORT_EVENTS_PREAGG_TTL_DAYS - 1

# Tables whose size is one count by team, keyed on their sort key. The count is shared across processes for a
# day: a team's persons or groups do not change enough within a day to move an estimate that is only good to
# a few times, and the alternative is one scan of the team's rows per query.
COUNTED_TABLES: frozenset[str] = frozenset({PERSONS_TABLE, GROUPS_TABLE})
TABLE_ROWS_CACHE_SECONDS = 24 * 60 * 60

# Tables whose rows arrive over time, sized as a daily rate the estimator scales to the query's range. The
# column is the one their sort key or partition is on, so the count reads only the window it asks for.
TIME_ORDERED_TABLES: dict[str, str] = {
    "sessions": "min_timestamp",
    "raw_sessions": "min_timestamp",
    "raw_sessions_v3": "session_timestamp",
}
DAILY_ROWS_WINDOW_DAYS = 7


@frozen
class EventVolume:
    """How many events a team ingested over a recent window, in total and per event name."""

    total: int
    by_event: Mapping[str, int]
    # Distinct days that had data. Divides ``total`` into a daily rate the estimator can scale to any range.
    days: int

    def __post_init__(self) -> None:
        if self.total < 0 or self.days < 0:
            raise ValueError("EventVolume counts cannot be negative")

    @property
    def per_day(self) -> float:
        return self.total / self.days if self.days else 0.0

    def event_fraction(self, event: str) -> float | None:
        """Share of the team's volume carried by one event name, or None when the name was never seen."""
        if not self.total:
            return None
        count = self.by_event.get(event)
        return None if count is None else count / self.total


class StatisticsProvider(Protocol):
    """Contract the estimator consumes. Every method returns ``None`` when the fact is unavailable."""

    def event_volume(self, team_id: int) -> EventVolume | None: ...

    def property_ndv(self, team_id: int, property_name: str) -> int | None:
        """How many distinct values an event property took recently."""
        ...

    def table_rows(self, team_id: int, table: str) -> int | None:
        """How many rows a ClickHouse table holds for the team. ``table`` is one of ``COUNTED_TABLES``."""
        ...

    def daily_rows(self, team_id: int, table: str) -> float | None:
        """How many rows a day the team adds to a time-ordered table. ``table`` is a ``TIME_ORDERED_TABLES`` key."""
        ...


class ClickHouseStatisticsProvider:
    """Reads statistics from the rollups ClickHouse already maintains.

    Instances are meant to live for one query: results are memoized per instance so several
    consumers in one planning pass share one lookup.
    """

    def __init__(self, *, today: date | None = None) -> None:
        self._today = today
        self._event_volume: dict[int, EventVolume | None] = {}
        self._property_ndv: dict[tuple[int, str], int | None] = {}
        self._table_rows: dict[tuple[int, str], int | None] = {}
        self._daily_rows: dict[tuple[int, str], float | None] = {}

    def event_volume(self, team_id: int) -> EventVolume | None:
        if team_id not in self._event_volume:
            self._event_volume[team_id] = self._load_event_volume(team_id)
        return self._event_volume[team_id]

    def property_ndv(self, team_id: int, property_name: str) -> int | None:
        key = (team_id, property_name)
        if key not in self._property_ndv:
            self._property_ndv[key] = self._load_property_ndv(team_id, property_name)
        return self._property_ndv[key]

    def table_rows(self, team_id: int, table: str) -> int | None:
        key = (team_id, table)
        if key not in self._table_rows:
            self._table_rows[key] = self._load_table_rows(team_id, table)
        return self._table_rows[key]

    def _load_table_rows(self, team_id: int, table: str) -> int | None:
        """Count the team's rows in a replicated table, once a day.

        The count runs without FINAL. A person or group that was updated has one row per version until the
        parts merge, so the count is an overcount, which is the right side to err on for a ceiling.
        """
        if table not in COUNTED_TABLES:
            return None
        cache_key = f"hogql_cost:table_rows:{team_id}:{table}"
        cached = cache.get(cache_key)
        if cached is not None:
            return int(cached)
        try:
            with tags_context(
                product=Product.INTERNAL,
                feature=Feature.SCHEMA_INTROSPECTION,
                team_id=team_id,
                plan_fingerprint=None,
                estimated_rows=None,
                estimated_bytes=None,
            ):
                # nosemgrep: clickhouse-fstring-param-audit - the f-string only interpolates a table name checked against COUNTED_TABLES; team_id is bound as a parameter
                rows = sync_execute(
                    f"SELECT count() FROM {settings.CLICKHOUSE_DATABASE}.{table} WHERE team_id = %(team_id)s",
                    {"team_id": team_id},
                    workload=Workload.OFFLINE,
                    team_id=team_id,
                    readonly=True,
                )
        except Exception:
            logger.warning("hogql_cost_table_rows_unavailable", team_id=team_id, table=table, exc_info=True)
            return None
        count = int(rows[0][0]) if rows else 0
        cache.set(cache_key, count, timeout=TABLE_ROWS_CACHE_SECONDS)
        return count

    def daily_rows(self, team_id: int, table: str) -> float | None:
        key = (team_id, table)
        if key not in self._daily_rows:
            self._daily_rows[key] = self._load_daily_rows(team_id, table)
        return self._daily_rows[key]

    def _load_daily_rows(self, team_id: int, table: str) -> float | None:
        """Average the team's rows over the last full days, once a day. Today is excluded because it is still filling."""
        time_column = TIME_ORDERED_TABLES.get(table)
        if time_column is None:
            return None
        cache_key = f"hogql_cost:daily_rows:{team_id}:{table}"
        cached = cache.get(cache_key)
        if cached is not None:
            return float(cached)
        today = self._today or date.today()
        since = today - timedelta(days=DAILY_ROWS_WINDOW_DAYS)
        try:
            with tags_context(
                product=Product.INTERNAL,
                feature=Feature.SCHEMA_INTROSPECTION,
                team_id=team_id,
                plan_fingerprint=None,
                estimated_rows=None,
                estimated_bytes=None,
            ):
                # nosemgrep: clickhouse-fstring-param-audit - the f-string only interpolates a table and column taken from TIME_ORDERED_TABLES; the rest is bound as parameters
                rows = sync_execute(
                    f"SELECT count() FROM {settings.CLICKHOUSE_DATABASE}.{table} "
                    f"WHERE team_id = %(team_id)s AND {time_column} >= %(since)s AND {time_column} < %(today)s",
                    {"team_id": team_id, "since": since, "today": today},
                    workload=Workload.OFFLINE,
                    team_id=team_id,
                    readonly=True,
                )
        except Exception:
            logger.warning("hogql_cost_daily_rows_unavailable", team_id=team_id, table=table, exc_info=True)
            return None
        per_day = (int(rows[0][0]) if rows else 0) / DAILY_ROWS_WINDOW_DAYS
        cache.set(cache_key, per_day, timeout=TABLE_ROWS_CACHE_SECONDS)
        return per_day

    def _load_event_volume(self, team_id: int) -> EventVolume | None:
        today = self._today or date.today()
        since = today - timedelta(days=EVENT_VOLUME_WINDOW_DAYS)
        try:
            with tags_context(
                product=Product.INTERNAL,
                feature=Feature.SCHEMA_INTROSPECTION,
                team_id=team_id,
                # A statistics lookup must not become an accuracy sample for its caller's query.
                plan_fingerprint=None,
                estimated_rows=None,
                estimated_bytes=None,
            ):
                # nosemgrep: clickhouse-fstring-param-audit - the f-string only interpolates a module constant table name; team_id is bound as a parameter
                rows = sync_execute(
                    f"""
                    SELECT date, event, sumMerge(event_count) AS event_count
                    FROM {settings.CLICKHOUSE_DATABASE}.{USAGE_REPORT_EVENTS_PREAGG_TABLE}
                    WHERE team_id = %(team_id)s AND date >= %(since)s AND date < %(today)s
                    GROUP BY date, event
                    """,
                    {"team_id": team_id, "since": since, "today": today},
                    workload=Workload.OFFLINE,
                    team_id=team_id,
                    readonly=True,
                )
        except Exception:
            # Statistics are advisory. Log and let the estimator run without them.
            logger.warning("hogql_cost_event_volume_unavailable", team_id=team_id, exc_info=True)
            return None

        if not rows:
            return None
        by_event: dict[str, int] = {}
        days: set[date] = set()
        for row_date, event, count in rows:
            by_event[str(event)] = by_event.get(str(event), 0) + int(count)
            days.add(row_date)
        return EventVolume(total=sum(by_event.values()), by_event=by_event, days=len(days))

    def _load_property_ndv(self, team_id: int, property_name: str) -> int | None:
        """Count the values the property-values aggregator recorded for one event property.

        Only the number of distinct values is read. ``property_count`` is not a frequency, because the
        aggregator can suppress a value it already emitted that day. The aggregator can also cap the values it
        keeps per key, so the count is a lower bound, which makes a filter look less selective than it is and
        widens the estimate. A property the aggregator excludes has no rows and reads as unknown.
        """
        try:
            with tags_context(
                product=Product.INTERNAL,
                feature=Feature.SCHEMA_INTROSPECTION,
                team_id=team_id,
                plan_fingerprint=None,
                estimated_rows=None,
                estimated_bytes=None,
            ):
                # nosemgrep: clickhouse-fstring-param-audit - the f-string only interpolates a module constant table name; team_id and the property name are bound as parameters
                rows = sync_execute(
                    f"""
                    SELECT uniq(property_value)
                    FROM {settings.CLICKHOUSE_DATABASE}.{PROPERTY_VALUES_TABLE}
                    WHERE team_id = %(team_id)s AND property_type = 'event' AND property_key = %(property_name)s
                    """,
                    {"team_id": team_id, "property_name": property_name},
                    workload=Workload.OFFLINE,
                    team_id=team_id,
                    readonly=True,
                )
        except Exception:
            logger.warning("hogql_cost_property_ndv_unavailable", team_id=team_id, exc_info=True)
            return None

        distinct_values = int(rows[0][0]) if rows else 0
        return distinct_values or None


class FixedStatisticsProvider:
    """Returns the statistics it was constructed with. For tests and for callers that already hold them."""

    def __init__(
        self,
        *,
        event_volume: Mapping[int, EventVolume] | None = None,
        property_ndv: Mapping[tuple[int, str], int] | None = None,
        table_rows: Mapping[tuple[int, str], int] | None = None,
        daily_rows: Mapping[tuple[int, str], float] | None = None,
    ) -> None:
        self._event_volume = dict(event_volume or {})
        self._property_ndv = dict(property_ndv or {})
        self._table_rows = dict(table_rows or {})
        self._daily_rows = dict(daily_rows or {})

    def event_volume(self, team_id: int) -> EventVolume | None:
        return self._event_volume.get(team_id)

    def property_ndv(self, team_id: int, property_name: str) -> int | None:
        return self._property_ndv.get((team_id, property_name))

    def table_rows(self, team_id: int, table: str) -> int | None:
        return self._table_rows.get((team_id, table))

    def daily_rows(self, team_id: int, table: str) -> float | None:
        return self._daily_rows.get((team_id, table))
