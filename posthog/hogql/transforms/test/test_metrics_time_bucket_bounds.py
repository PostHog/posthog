from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.hogql.context import HogQLContext
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_and_print_ast


class TestMetricsTimeBucketBounds(BaseTest):
    def _print(self, query: str) -> str:
        context = HogQLContext(team_id=self.team.pk, team=self.team, enable_select_queries=True)
        return prepare_and_print_ast(parse_select(query), context, "clickhouse")[0]

    @parameterized.expand(
        [
            ("gte", "timestamp >= now() - INTERVAL 2 HOUR", "greaterOrEquals(metrics4_view.time_bucket"),
            ("gt", "timestamp > now() - INTERVAL 2 HOUR", "greaterOrEquals(metrics4_view.time_bucket"),
            ("lt", "timestamp < now()", "lessOrEquals(metrics4_view.time_bucket"),
            ("lte", "timestamp <= now()", "lessOrEquals(metrics4_view.time_bucket"),
            ("flipped", "now() - INTERVAL 2 HOUR <= timestamp", "greaterOrEquals(metrics4_view.time_bucket"),
            ("literal", "timestamp >= toDateTime('2026-09-25 10:17:00')", "greaterOrEquals(metrics4_view.time_bucket"),
        ]
    )
    def test_adds_hour_bound(self, _name: str, where: str, expected: str):
        sql = self._print(f"SELECT count() FROM posthog.metrics WHERE team_id = 1 AND {where}")
        assert expected in sql
        assert "toStartOfHour(toTimeZone(" in sql

    def test_adds_both_bounds_with_table_alias(self):
        sql = self._print(
            "SELECT count() FROM posthog.metrics AS m WHERE m.timestamp >= now() - INTERVAL 1 HOUR AND m.timestamp < now()"
        )
        assert "greaterOrEquals(m.time_bucket" in sql
        assert "lessOrEquals(m.time_bucket" in sql

    @parameterized.expand(
        [
            ("column_bound", "SELECT count() FROM posthog.metrics WHERE timestamp >= observed_timestamp"),
            ("inside_or", "SELECT count() FROM posthog.metrics WHERE timestamp >= now() OR value > 1"),
            ("equality", "SELECT count() FROM posthog.metrics WHERE timestamp = now()"),
            ("other_table", "SELECT count() FROM events WHERE timestamp >= now()"),
        ]
    )
    def test_leaves_other_filters_alone(self, _name: str, query: str):
        assert "time_bucket" not in self._print(query)
