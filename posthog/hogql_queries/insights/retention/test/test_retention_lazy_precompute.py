from datetime import UTC, datetime

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, _create_person, flush_persons_and_events
from unittest.mock import patch

from django.test import override_settings

from posthog.hogql import ast
from posthog.hogql.parser import parse_select

from posthog.clickhouse.client import sync_execute
from posthog.hogql_queries.insights.retention.retention_lazy_precompute import (
    INSERT_QUERY_TEMPLATE,
    LAZY_TTL_SECONDS,
    ensure_retention_precomputed,
)

from products.analytics_platform.backend.lazy_computation.lazy_computation_executor import LazyComputationTable
from products.analytics_platform.backend.models.preaggregation_job import PreaggregationJob


class TestRetentionLazyPrecomputeUnit:
    """Unit-level tests for the precompute template + wrapper. No CH required."""

    def test_insert_template_parses(self) -> None:
        # Template uses `{time_window_min}` / `{time_window_max}` placeholders that
        # `ensure_precomputed` substitutes per job. Verify it parses with sentinel
        # values so we catch syntax regressions early.
        parsed = parse_select(
            INSERT_QUERY_TEMPLATE,
            placeholders={
                "time_window_min": ast.Constant(value=datetime(2026, 1, 1, tzinfo=UTC)),
                "time_window_max": ast.Constant(value=datetime(2026, 1, 2, tzinfo=UTC)),
            },
        )
        assert parsed is not None

    def test_insert_template_emits_expected_columns(self) -> None:
        # SELECT must emit exactly the payload columns the table expects between
        # team_id (added by framework) and expires_at (added by framework). The
        # framework builds the INSERT column list from these aliases, so missing
        # columns fall back to their table DEFAULTs (notably computed_at).
        parsed = parse_select(
            INSERT_QUERY_TEMPLATE,
            placeholders={
                "time_window_min": ast.Constant(value=datetime(2026, 1, 1, tzinfo=UTC)),
                "time_window_max": ast.Constant(value=datetime(2026, 1, 2, tzinfo=UTC)),
            },
        )
        aliases = [
            expr.alias if isinstance(expr, ast.Alias) else None  # type: ignore[attr-defined]
            for expr in parsed.select  # type: ignore[union-attr]
        ]
        assert aliases == ["day", "actor_id", "group_type_index", "event", "first_ts"]

    def test_ttl_ladder_shape(self) -> None:
        # Tighter TTLs for newer windows, "default" fallback for older. Mirrors the
        # web analytics precedent so the lazy_computation framework's TTL parser
        # accepts our values.
        assert "default" in LAZY_TTL_SECONDS
        assert LAZY_TTL_SECONDS["0d"] < LAZY_TTL_SECONDS["1d"] < LAZY_TTL_SECONDS["7d"] <= LAZY_TTL_SECONDS["default"]

    @patch("posthog.hogql_queries.insights.retention.retention_lazy_precompute.ensure_precomputed")
    def test_ensure_retention_precomputed_routes_to_framework(self, mock_ensure) -> None:
        team = object()
        ensure_retention_precomputed(
            team=team,  # type: ignore[arg-type]
            time_range_start=datetime(2026, 1, 1, tzinfo=UTC),
            time_range_end=datetime(2026, 1, 8, tzinfo=UTC),
        )
        mock_ensure.assert_called_once_with(
            team=team,
            insert_query=INSERT_QUERY_TEMPLATE,
            time_range_start=datetime(2026, 1, 1, tzinfo=UTC),
            time_range_end=datetime(2026, 1, 8, tzinfo=UTC),
            ttl_seconds=LAZY_TTL_SECONDS,
            table=LazyComputationTable.RETENTION_ACTOR_EVENT_DAY,
            placeholders={},
            query_type="retention_actor_event_day",
        )


@override_settings(IN_UNIT_TESTING=True)
class TestRetentionLazyPrecomputeClickhouse(ClickhouseTestMixin, APIBaseTest):
    """End-to-end tests against ClickHouse: generate events, materialise, verify rows."""

    def setUp(self) -> None:
        super().setUp()
        PreaggregationJob.objects.filter(team_id=self.team.pk).delete()
        # Mirrors web analytics precompute tests: the framework derives expires_at
        # from the (test) clock, so precompute rows are "born expired" relative to
        # the real CH server clock. Stop TTL merges so they're not dropped between
        # the precompute INSERT and the verifying SELECT.
        sync_execute("SYSTEM STOP TTL MERGES sharded_retention_actor_event_day")

    def test_materialises_one_row_per_actor_day_event(self) -> None:
        # Two actors, four events on 2026-01-02. p1 has two $pageview events on the
        # same day so we exercise the (actor, day, event) collapse — both should
        # produce ONE pre-agg row with first_ts = the earlier of the two timestamps.
        _create_person(team_id=self.team.pk, distinct_ids=["p1"], properties={})
        _create_person(team_id=self.team.pk, distinct_ids=["p2"], properties={})
        _create_event(team=self.team, event="$pageview", distinct_id="p1", timestamp="2026-01-02T09:00:00Z")
        _create_event(team=self.team, event="$pageview", distinct_id="p1", timestamp="2026-01-02T15:00:00Z")
        _create_event(team=self.team, event="$screen", distinct_id="p1", timestamp="2026-01-02T10:00:00Z")
        _create_event(team=self.team, event="$pageview", distinct_id="p2", timestamp="2026-01-02T12:00:00Z")
        flush_persons_and_events()

        result = ensure_retention_precomputed(
            team=self.team,
            time_range_start=datetime(2026, 1, 2, tzinfo=UTC),
            time_range_end=datetime(2026, 1, 3, tzinfo=UTC),
        )
        assert result.ready
        assert len(result.job_ids) == 1

        rows = sync_execute(
            """
            SELECT day, event, first_ts
            FROM retention_actor_event_day
            WHERE team_id = %(team_id)s AND job_id = %(job_id)s
            ORDER BY event, first_ts
            """,
            {"team_id": self.team.pk, "job_id": result.job_ids[0]},
        )

        # 3 rows: (p1, $pageview), (p1, $screen), (p2, $pageview) — the two $pageview
        # events for p1 collapse to one row.
        assert len(rows) == 3
        days = {r[0] for r in rows}
        assert days == {datetime(2026, 1, 2).date()}
        events_per_row = sorted(r[1] for r in rows)
        assert events_per_row == ["$pageview", "$pageview", "$screen"]

        # The collapsed (p1, $pageview) row should carry the EARLIER timestamp (09:00),
        # not 15:00. The pageview row with the smaller first_ts is p1's.
        pageview_rows = [r for r in rows if r[1] == "$pageview"]
        assert min(r[2] for r in pageview_rows).hour == 9

    def test_excludes_events_outside_window(self) -> None:
        # An event one hour before the window must not appear in the materialisation.
        _create_person(team_id=self.team.pk, distinct_ids=["p1"], properties={})
        _create_event(team=self.team, event="$pageview", distinct_id="p1", timestamp="2026-01-01T23:00:00Z")
        _create_event(team=self.team, event="$pageview", distinct_id="p1", timestamp="2026-01-02T01:00:00Z")
        _create_event(team=self.team, event="$pageview", distinct_id="p1", timestamp="2026-01-03T01:00:00Z")
        flush_persons_and_events()

        result = ensure_retention_precomputed(
            team=self.team,
            time_range_start=datetime(2026, 1, 2, tzinfo=UTC),
            time_range_end=datetime(2026, 1, 3, tzinfo=UTC),
        )
        assert result.ready

        rows = sync_execute(
            """
            SELECT count(), min(first_ts), max(first_ts)
            FROM retention_actor_event_day
            WHERE team_id = %(team_id)s AND job_id = %(job_id)s
            """,
            {"team_id": self.team.pk, "job_id": result.job_ids[0]},
        )
        # Exactly one row (Jan 2 event); the Jan 1 and Jan 3 events must not bleed in.
        assert rows[0][0] == 1
        assert rows[0][1].day == 2
        assert rows[0][2].day == 2

    def test_other_teams_excluded(self) -> None:
        # Events from a different team must not appear in this team's materialisation.
        # ensure_precomputed filters by team_id in its INSERT wrapper; this asserts
        # that filter is doing its job.
        _create_person(team_id=self.team.pk, distinct_ids=["p1"], properties={})
        _create_event(team=self.team, event="$pageview", distinct_id="p1", timestamp="2026-01-02T09:00:00Z")
        # Insert directly into another team — using a low ID that won't clash.
        other_team_id = self.team.pk + 100000
        sync_execute(
            "INSERT INTO sharded_events (uuid, event, properties, timestamp, team_id, distinct_id, person_id) "
            "VALUES (generateUUIDv4(), %(event)s, '{}', %(ts)s, %(team_id)s, 'other-p1', generateUUIDv4())",
            {"event": "$pageview", "ts": "2026-01-02 10:00:00", "team_id": other_team_id},
        )
        flush_persons_and_events()

        result = ensure_retention_precomputed(
            team=self.team,
            time_range_start=datetime(2026, 1, 2, tzinfo=UTC),
            time_range_end=datetime(2026, 1, 3, tzinfo=UTC),
        )
        rows = sync_execute(
            "SELECT count() FROM retention_actor_event_day WHERE job_id = %(job_id)s",
            {"job_id": result.job_ids[0]},
        )
        # Just my team's one row; the other team's event must not bleed in.
        assert rows[0][0] == 1
