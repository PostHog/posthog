"""Tests for how each SQL dialect binds constant values."""

from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.hogql import ast
from posthog.hogql.constants import HogQLDialect
from posthog.hogql.context import HogQLContext
from posthog.hogql.printer import print_prepared_ast


class TestDialectConstantBinding(BaseTest):
    # Every printer below PostgresPrinter used to escape constants through SQLValueEscaper, which
    # only models the `hogql` and `clickhouse` dialects. Temporal and UUID values therefore came out
    # as toDate(...)/toDateTime(...)/toUUID(...), none of which exist in Postgres, MySQL, Snowflake,
    # Redshift, or DuckDB. Reachable in production from a {filters} date range on a direct-SQL
    # source, where replace_filters injects a real datetime constant.
    maxDiff = None

    NON_CLICKHOUSE_DIALECTS: list[tuple[str, HogQLDialect]] = [
        ("postgres", "postgres"),
        ("mysql", "mysql"),
        ("snowflake", "snowflake"),
        ("redshift", "redshift"),
        ("duckdb", "duckdb"),
        ("trino", "trino"),
    ]

    def _constant(self, value: Any, dialect: HogQLDialect) -> tuple[str, dict[str, Any]]:
        context = HogQLContext(team_id=self.team.pk, enable_select_queries=True)
        printed = print_prepared_ast(ast.Constant(value=value), context=context, dialect=dialect)
        return printed, context.values

    @parameterized.expand(NON_CLICKHOUSE_DIALECTS)
    def test_temporal_and_uuid_constants_are_bound(self, _name: str, dialect: HogQLDialect):
        cases: list[tuple[Any, Any]] = [
            (date(2024, 1, 1), date(2024, 1, 1)),
            (datetime(2024, 1, 1, 12, 0, tzinfo=UTC), datetime(2024, 1, 1, 12, 0, tzinfo=UTC)),
            # UUIDs bind as strings: these engines model them as text, and the MySQL and Snowflake
            # drivers will not bind a UUID object.
            (UUID("019f8904-44e9-0000-4c77-dc6aed04b8ff"), "019f8904-44e9-0000-4c77-dc6aed04b8ff"),
        ]
        for value, expected_bound in cases:
            printed, values = self._constant(value, dialect)
            self.assertEqual(printed, "%(hogql_val_0)s", f"{dialect} inlined {type(value).__name__}")
            self.assertEqual(list(values.values()), [expected_bound])

    @parameterized.expand(NON_CLICKHOUSE_DIALECTS)
    def test_simple_scalar_constants_stay_inline(self, _name: str, dialect: HogQLDialect):
        # None/bool/int/float have no dialect-specific syntax, so they stay inlined and unbound.
        # Guards against the fix over-reaching into values that were never broken.
        for value, expected in [(None, "NULL"), (True, "true"), (42, "42"), (1.5, "1.5")]:
            printed, values = self._constant(value, dialect)
            self.assertEqual(printed, expected)
            self.assertEqual(values, {})

    def test_clickhouse_still_inlines_temporal_constants(self):
        # ClickHouse is where toDate()/toDateTime64() are correct, so it must keep inlining them.
        printed, values = self._constant(date(2024, 1, 1), "clickhouse")
        self.assertEqual(printed, "toDate('2024-01-01')")
        self.assertEqual(values, {})
