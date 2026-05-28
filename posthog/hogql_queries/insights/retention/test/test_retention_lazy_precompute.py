from datetime import UTC, datetime

from unittest import TestCase
from unittest.mock import patch

from posthog.hogql import ast
from posthog.hogql.parser import parse_select

from posthog.hogql_queries.insights.retention.retention_lazy_precompute import (
    INSERT_QUERY_TEMPLATE,
    LAZY_TTL_SECONDS,
    ensure_retention_precomputed,
)

from products.analytics_platform.backend.lazy_computation.lazy_computation_executor import LazyComputationTable


class TestRetentionLazyPrecompute(TestCase):
    """Unit-level tests for the retention precompute foundation. The CH end-to-end
    tests are intentionally deferred to the read-path PR — that's where the
    materialisation + read together make sense to exercise, and where we'll have
    a stable test fixture set up for the pre-agg table."""

    def test_insert_template_parses(self) -> None:
        # Template uses `{time_window_min}` / `{time_window_max}` placeholders that
        # `ensure_precomputed` substitutes per job. Verify it parses with sentinel
        # values for those placeholders so we catch syntax regressions early.
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
        # framework builds the INSERT column list from the SELECT's aliases, so
        # missing columns fall back to their table DEFAULTs (notably computed_at).
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
        # Thin wrapper assertion: ensure_retention_precomputed routes to the
        # framework with the right table, TTL ladder, time window, and query_type.
        team = object()  # opaque — we only assert it's passed through
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
