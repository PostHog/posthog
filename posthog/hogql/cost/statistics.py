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

import structlog

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.clickhouse.workload import Workload
from posthog.dataclasses import frozen
from posthog.models.usage_report_events_preagg.sql import (
    USAGE_REPORT_EVENTS_PREAGG_TABLE,
    USAGE_REPORT_EVENTS_PREAGG_TTL_DAYS,
)

logger = structlog.get_logger(__name__)

# The rollup drops parts past its TTL, so a window this long is the most it can answer. Today is excluded
# because it is still filling, and a team that stopped sending has fewer days than the window, so callers
# scale by ``EventVolume.days`` rather than dividing by the window they asked for.
EVENT_VOLUME_WINDOW_DAYS = USAGE_REPORT_EVENTS_PREAGG_TTL_DAYS - 1


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


class ClickHouseStatisticsProvider:
    """Reads statistics from the rollups ClickHouse already maintains.

    Instances are meant to live for one query: results are memoized per instance so several
    consumers in one planning pass share one lookup.
    """

    def __init__(self, *, today: date | None = None) -> None:
        self._today = today
        self._event_volume: dict[int, EventVolume | None] = {}

    def event_volume(self, team_id: int) -> EventVolume | None:
        if team_id not in self._event_volume:
            self._event_volume[team_id] = self._load_event_volume(team_id)
        return self._event_volume[team_id]

    def _load_event_volume(self, team_id: int) -> EventVolume | None:
        today = self._today or date.today()
        since = today - timedelta(days=EVENT_VOLUME_WINDOW_DAYS)
        try:
            with tags_context(product=Product.INTERNAL, feature=Feature.SCHEMA_INTROSPECTION, team_id=team_id):
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


class FixedStatisticsProvider:
    """Returns the statistics it was constructed with. For tests and for callers that already hold them."""

    def __init__(self, *, event_volume: Mapping[int, EventVolume] | None = None) -> None:
        self._event_volume = dict(event_volume or {})

    def event_volume(self, team_id: int) -> EventVolume | None:
        return self._event_volume.get(team_id)
