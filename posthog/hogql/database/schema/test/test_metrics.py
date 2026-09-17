import datetime as dt
from typing import Optional, cast

from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_and_print_ast
from posthog.hogql.query import HogQLQueryExecutor, execute_hogql_query
from posthog.hogql.resolver import resolve_types

from products.metrics.backend.tests._seeder import seed_metric, truncate_metrics_tables

METRICS_TABLE = "posthog.metrics"


class TestMetricsSeriesJoin(ClickhouseTestMixin, APIBaseTest):
    """`metrics` should expose series labels (attributes, resource_attributes) via a lazy join to `metric_series`."""

    def _select(self, query: str, placeholders: Optional[dict[str, ast.Expr]] = None) -> ast.SelectQuery:
        return cast(ast.SelectQuery, parse_select(query, placeholders=placeholders))

    def _print_clickhouse(self, query: str) -> str:
        node = self._select(query)
        return prepare_and_print_ast(
            node,
            HogQLContext(team_id=self.team.pk, enable_select_queries=True),
            dialect="clickhouse",
        )[0]

    def test_metrics_table_exposes_series_lazy_join(self):
        from posthog.hogql.database.database import Database
        from posthog.hogql.modifiers import create_default_modifiers_for_team

        modifiers = create_default_modifiers_for_team(self.team)
        sources = Database._fetch_sources(team=self.team, modifiers=modifiers)
        db = Database._build_from_sources(sources)
        metrics_table = db.get_table("posthog.metrics")
        assert "series" in metrics_table.fields, "metrics table must expose a `series` field joining metric_series"

    def test_select_series_attributes_joins_metric_series(self):
        sql = self._print_clickhouse(f"SELECT series.attributes FROM {METRICS_TABLE} LIMIT 10")
        assert "metric_series" in sql, f"expected a join against metric_series, got:\n{sql}"
        assert "attributes" in sql

    def test_select_series_resource_attributes_joins_metric_series(self):
        sql = self._print_clickhouse(f"SELECT series.resource_attributes FROM {METRICS_TABLE} LIMIT 10")
        assert "metric_series" in sql
        assert "resource_attributes" in sql

    def test_series_join_keys_on_series_fingerprint(self):
        sql = self._print_clickhouse(f"SELECT series.attributes FROM {METRICS_TABLE} LIMIT 10")
        assert sql.replace(" ", "").count("series_fingerprint") >= 2

    def test_execute_query_grouping_by_label(self):
        # End to end: a query that groups metric data points by a label key must run.
        executor = HogQLQueryExecutor(
            query=f"SELECT series.attributes['service.name'] AS svc, count() FROM {METRICS_TABLE} GROUP BY svc LIMIT 10",
            team=self.team,
            query_type="HogQLQuery",
        )
        sql, _context = executor.generate_clickhouse_sql()
        assert "metric_series" in sql
        assert "attributes" in sql

    def test_end_to_end_group_by_label_returns_seeded_label(self):
        # Seed a metric whose series carries a `route` label, then group data points by it through
        # the lazy join. This is the exact thing the SQL explorer customer could not do.
        truncate_metrics_tables()
        seed_metric(
            team_id=self.team.pk,
            metric_name="http_requests_total",
            metric_type="sum",
            service_name="web",
            points=[(dt.datetime(2026, 1, 1, 0, 0, 0, tzinfo=dt.UTC), 1.0)],
            labels={"route": "/checkout"},
        )
        response = execute_hogql_query(
            f"SELECT series.attributes['route'] AS route, count() AS c "
            f"FROM {METRICS_TABLE} WHERE metric_name = 'http_requests_total' GROUP BY route",
            self.team,
        )
        routes = {row[0] for row in response.results}
        assert "/checkout" in routes, f"expected the seeded route label, got: {response.results}"

    def test_resolver_resolves_series_field_type(self):
        from posthog.hogql.database.database import Database
        from posthog.hogql.modifiers import create_default_modifiers_for_team

        modifiers = create_default_modifiers_for_team(self.team)
        sources = Database._fetch_sources(team=self.team, modifiers=modifiers)
        database = Database._build_from_sources(sources)
        node = self._select(f"SELECT series.attributes FROM {METRICS_TABLE}")
        context = HogQLContext(database=database, team_id=self.team.pk, enable_select_queries=True)
        resolved = resolve_types(node, context, dialect="clickhouse")
        assert resolved is not None
