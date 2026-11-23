import hashlib
from collections.abc import Callable, Iterable
from dataclasses import astuple
from datetime import UTC, datetime
from typing import Any

from django.conf import settings
from django.core.cache import caches

import structlog

from posthog.hogql.escape_sql import escape_clickhouse_identifier

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.workload import Workload
from posthog.dataclasses import frozen
from posthog.models.distinct_id_usage.sql import TABLE_BASE_NAME
from posthog.models.event_ingestion_restriction_config import EventIngestionRestrictionConfig
from posthog.models.team.team import Team

logger = structlog.get_logger(__name__)

QUERY_SETTINGS = {"max_execution_time": 30}
# Four ClickHouse queries of up to 30 seconds each run per report. Staff reload and share these pages
# during incidents, so the event counts are reused for a few minutes. Restrictions are never cached.
REPORT_CACHE_SECONDS = 300
# A cache alias with the JSON serializer, so reading the report never unpickles what sits in Redis.
REPORT_CACHE_ALIAS = "distinct_id_usage_report"


@frozen
class UsageThresholds:
    high_usage_percentage: int
    high_usage_min_team_events: int
    high_usage_min_distinct_id_events: int
    high_cardinality: int
    distinct_id_burst: int
    team_burst: int


@frozen
class TokenRestriction:
    """An analytics ingestion restriction on a project token. An empty `distinct_ids` restricts every distinct ID."""

    id: str
    restriction_type: str
    label: str
    distinct_ids: tuple[str, ...]


@frozen
class HighUsageDistinctId:
    team_id: int
    token: str
    distinct_id: str
    event_count: int
    team_event_count: int
    percentage: float
    restrictions: tuple[TokenRestriction, ...]


@frozen
class HighCardinalityTeam:
    team_id: int
    token: str
    distinct_id_count: int
    restrictions: tuple[TokenRestriction, ...]


@frozen
class DistinctIdBurst:
    team_id: int
    token: str
    distinct_id: str
    minute: datetime
    event_count: int
    restrictions: tuple[TokenRestriction, ...]


@frozen
class TeamBurst:
    team_id: int
    token: str
    minute: datetime
    event_count: int
    restrictions: tuple[TokenRestriction, ...]


@frozen
class DistinctIdUsageReport:
    high_usage: tuple[HighUsageDistinctId, ...]
    high_cardinality: tuple[HighCardinalityTeam, ...]
    distinct_id_bursts: tuple[DistinctIdBurst, ...]
    team_bursts: tuple[TeamBurst, ...]
    # One line per query that failed. The other queries still report their rows.
    errors: tuple[str, ...]
    computed_at: datetime


@frozen
class _EventCounts:
    high_usage: list[tuple]
    high_cardinality: list[tuple]
    distinct_id_bursts: list[tuple]
    team_bursts: list[tuple]
    errors: tuple[str, ...]
    computed_at: datetime

    def to_json(self) -> dict[str, Any]:
        return {
            "high_usage": [list(row) for row in self.high_usage],
            "high_cardinality": [list(row) for row in self.high_cardinality],
            "distinct_id_bursts": [
                [team_id, distinct_id, minute.isoformat(), count]
                for team_id, distinct_id, minute, count in self.distinct_id_bursts
            ],
            "team_bursts": [[team_id, minute.isoformat(), count] for team_id, minute, count in self.team_bursts],
            "computed_at": self.computed_at.isoformat(),
        }

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> "_EventCounts":
        return cls(
            high_usage=[tuple(row) for row in payload["high_usage"]],
            high_cardinality=[tuple(row) for row in payload["high_cardinality"]],
            distinct_id_bursts=[
                (team_id, distinct_id, datetime.fromisoformat(minute), count)
                for team_id, distinct_id, minute, count in payload["distinct_id_bursts"]
            ],
            team_bursts=[
                (team_id, datetime.fromisoformat(minute), count) for team_id, minute, count in payload["team_bursts"]
            ],
            errors=(),
            computed_at=datetime.fromisoformat(payload["computed_at"]),
        )


@frozen
class RestrictionChange:
    label: str
    created: bool
    added: bool


class RestrictionRefused(Exception):
    pass


class DistinctIdUsageQueries:
    """Reads the distinct_id_usage table, which keeps per-minute event counts per distinct ID for 7 days."""

    @staticmethod
    def _execute(query: str, params: dict[str, Any]) -> list[tuple]:
        # Staff wait on the console page for these results.
        return sync_execute(query, params, settings=QUERY_SETTINGS, workload=Workload.ONLINE)

    @staticmethod
    def _table() -> str:
        db = escape_clickhouse_identifier(settings.CLICKHOUSE_DATABASE)
        tbl = escape_clickhouse_identifier(TABLE_BASE_NAME)
        return f"{db}.{tbl}"

    @classmethod
    def high_usage(cls, dt_from: datetime, dt_to: datetime, thresholds: UsageThresholds) -> list[tuple]:
        query = """
            WITH team_totals AS (
                SELECT team_id, sum(event_count) as total_events
                FROM {table}
                WHERE minute >= %(dt_from)s AND minute < %(dt_to)s
                GROUP BY team_id
                HAVING total_events >= %(min_events_threshold)s
            ),
            distinct_id_totals AS (
                SELECT team_id, distinct_id, sum(event_count) as event_count
                FROM {table}
                WHERE minute >= %(dt_from)s AND minute < %(dt_to)s
                GROUP BY team_id, distinct_id
            )
            SELECT d.team_id, d.distinct_id, d.event_count, t.total_events,
                   round(d.event_count * 100.0 / t.total_events, 2) as percentage
            FROM distinct_id_totals d
            JOIN team_totals t ON d.team_id = t.team_id
            WHERE d.event_count * 100.0 / t.total_events >= %(threshold)s
              AND d.event_count >= %(distinct_id_min_events)s
            ORDER BY d.event_count DESC
            LIMIT 100
            """.format(table=cls._table())
        return cls._execute(
            query,
            {
                "dt_from": dt_from,
                "dt_to": dt_to,
                "threshold": thresholds.high_usage_percentage,
                "min_events_threshold": thresholds.high_usage_min_team_events,
                "distinct_id_min_events": thresholds.high_usage_min_distinct_id_events,
            },
        )

    @classmethod
    def high_cardinality(cls, dt_from: datetime, dt_to: datetime, thresholds: UsageThresholds) -> list[tuple]:
        query = """
            SELECT team_id, uniq(distinct_id) as distinct_id_count
            FROM {table}
            WHERE minute >= %(dt_from)s AND minute < %(dt_to)s
            GROUP BY team_id
            HAVING distinct_id_count >= %(threshold)s
            ORDER BY distinct_id_count DESC
            LIMIT 100
            """.format(table=cls._table())
        return cls._execute(query, {"dt_from": dt_from, "dt_to": dt_to, "threshold": thresholds.high_cardinality})

    @classmethod
    def distinct_id_bursts(cls, dt_from: datetime, dt_to: datetime, thresholds: UsageThresholds) -> list[tuple]:
        query = """
            SELECT team_id, distinct_id, minute, event_count
            FROM {table}
            WHERE minute >= %(dt_from)s AND minute < %(dt_to)s
              AND event_count >= %(threshold)s
            ORDER BY event_count DESC
            LIMIT 100
            """.format(table=cls._table())
        return cls._execute(query, {"dt_from": dt_from, "dt_to": dt_to, "threshold": thresholds.distinct_id_burst})

    @classmethod
    def team_bursts(cls, dt_from: datetime, dt_to: datetime, thresholds: UsageThresholds) -> list[tuple]:
        query = """
            SELECT team_id, minute, sum(event_count) as total_events
            FROM {table}
            WHERE minute >= %(dt_from)s AND minute < %(dt_to)s
            GROUP BY team_id, minute
            HAVING total_events >= %(threshold)s
            ORDER BY total_events DESC
            LIMIT 100
            """.format(table=cls._table())
        return cls._execute(query, {"dt_from": dt_from, "dt_to": dt_to, "threshold": thresholds.team_burst})


class DistinctIdUsage:
    """Finds distinct IDs and teams that send unusually many events, and restricts their ingestion."""

    @staticmethod
    def _analytics_restrictions(tokens: Iterable[str]) -> dict[str, tuple[TokenRestriction, ...]]:
        by_token: dict[str, list[TokenRestriction]] = {}
        for restriction in EventIngestionRestrictionConfig.objects.filter(
            token__in=list(tokens), pipelines__contains=["analytics"]
        ):
            by_token.setdefault(restriction.token, []).append(
                TokenRestriction(
                    id=str(restriction.pk),
                    restriction_type=restriction.restriction_type,
                    label=restriction.get_restriction_type_display().capitalize(),
                    distinct_ids=tuple(restriction.distinct_ids or ()),
                )
            )
        return {token: tuple(restrictions) for token, restrictions in by_token.items()}

    @staticmethod
    def _cache_key(dt_from: datetime, dt_to: datetime, thresholds: UsageThresholds) -> str:
        digest = hashlib.sha256(repr((dt_from, dt_to, astuple(thresholds))).encode()).hexdigest()
        return f"distinct_id_usage_report:{digest}"

    @classmethod
    def _event_counts(cls, dt_from: datetime, dt_to: datetime, thresholds: UsageThresholds) -> _EventCounts:
        cache_key = cls._cache_key(dt_from, dt_to, thresholds)
        # Staff open this report during incidents, so a cache outage costs the speedup, never the report.
        try:
            cached = caches[REPORT_CACHE_ALIAS].get(cache_key)
            if cached is not None:
                return _EventCounts.from_json(cached)
        except Exception:
            logger.exception("distinct_id_usage_cache_read_failed")

        errors: list[str] = []

        def run(name: str, query: Callable[[datetime, datetime, UsageThresholds], list[tuple]]) -> list[tuple]:
            try:
                return query(dt_from, dt_to, thresholds)
            except Exception as error:
                logger.exception("distinct_id_usage_query_failed", query=name)
                errors.append(f"The {name} query failed: {error}")
                return []

        counts = _EventCounts(
            high_usage=run("high usage", DistinctIdUsageQueries.high_usage),
            high_cardinality=run("high cardinality", DistinctIdUsageQueries.high_cardinality),
            distinct_id_bursts=run("burst by distinct ID", DistinctIdUsageQueries.distinct_id_bursts),
            team_bursts=run("burst by team", DistinctIdUsageQueries.team_bursts),
            errors=tuple(errors),
            computed_at=datetime.now(tz=UTC),
        )
        # A failed query is not cached, so staff can retry without waiting for the cache to expire.
        if not counts.errors:
            try:
                caches[REPORT_CACHE_ALIAS].set(cache_key, counts.to_json(), timeout=REPORT_CACHE_SECONDS)
            except Exception:
                logger.exception("distinct_id_usage_cache_write_failed")
        return counts

    @classmethod
    def report(cls, dt_from: datetime, dt_to: datetime, thresholds: UsageThresholds) -> DistinctIdUsageReport:
        counts = cls._event_counts(dt_from, dt_to, thresholds)
        high_usage = counts.high_usage
        high_cardinality = counts.high_cardinality
        distinct_id_bursts = counts.distinct_id_bursts
        team_bursts = counts.team_bursts

        team_ids = {row[0] for rows in (high_usage, high_cardinality, distinct_id_bursts, team_bursts) for row in rows}
        tokens: dict[int, str] = (
            dict(Team.objects.filter(id__in=team_ids).values_list("id", "api_token")) if team_ids else {}
        )
        restrictions = cls._analytics_restrictions(tokens.values()) if tokens else {}

        def token_of(team_id: int) -> str:
            return tokens.get(team_id, "")

        def restrictions_of(team_id: int) -> tuple[TokenRestriction, ...]:
            return restrictions.get(token_of(team_id), ())

        return DistinctIdUsageReport(
            high_usage=tuple(
                HighUsageDistinctId(
                    team_id=team_id,
                    token=token_of(team_id),
                    distinct_id=distinct_id,
                    event_count=event_count,
                    team_event_count=team_event_count,
                    percentage=percentage,
                    restrictions=restrictions_of(team_id),
                )
                for team_id, distinct_id, event_count, team_event_count, percentage in high_usage
            ),
            high_cardinality=tuple(
                HighCardinalityTeam(
                    team_id=team_id,
                    token=token_of(team_id),
                    distinct_id_count=distinct_id_count,
                    restrictions=restrictions_of(team_id),
                )
                for team_id, distinct_id_count in high_cardinality
            ),
            distinct_id_bursts=tuple(
                DistinctIdBurst(
                    team_id=team_id,
                    token=token_of(team_id),
                    distinct_id=distinct_id,
                    minute=minute,
                    event_count=event_count,
                    restrictions=restrictions_of(team_id),
                )
                for team_id, distinct_id, minute, event_count in distinct_id_bursts
            ),
            team_bursts=tuple(
                TeamBurst(
                    team_id=team_id,
                    token=token_of(team_id),
                    minute=minute,
                    event_count=event_count,
                    restrictions=restrictions_of(team_id),
                )
                for team_id, minute, event_count in team_bursts
            ),
            errors=counts.errors,
            computed_at=counts.computed_at,
        )

    @staticmethod
    def restrict(token: str, restriction_type: str, distinct_id: str) -> RestrictionChange:
        existing = EventIngestionRestrictionConfig.objects.filter(
            token=token, restriction_type=restriction_type
        ).first()
        if existing is not None and "analytics" not in (existing.pipelines or []):
            # One row per token and type, so a row scoped to other pipelines cannot also cover analytics.
            raise RestrictionRefused(
                f"The {existing.get_restriction_type_display().capitalize()} restriction of this project applies to "
                f"{', '.join(existing.pipelines or [])} only, not analytics, so nothing changed. "
                "Add analytics to its pipelines first."
            )
        if existing is not None and not existing.distinct_ids:
            # An empty list matches every distinct ID, so adding one would narrow the restriction to that one.
            raise RestrictionRefused(
                f"The {existing.get_restriction_type_display().capitalize()} restriction of this project applies to "
                "every distinct ID already, so nothing changed."
            )
        restriction, created, added = EventIngestionRestrictionConfig.add_distinct_id_for_token(
            token, restriction_type, distinct_id
        )
        return RestrictionChange(
            label=restriction.get_restriction_type_display().capitalize(), created=created, added=added
        )
