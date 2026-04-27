from posthog.test.base import BaseTest

from posthog.schema import ExperimentDataWarehouseNode

from posthog.hogql import ast
from posthog.hogql.parser import parse_select

from posthog.hogql_queries.experiments.metric_source import MetricSourceInfo


class TestHogQLInjectionPrevention(BaseTest):
    """Verify that user-controlled table_name and timestamp_field from
    ExperimentDataWarehouseNode cannot inject arbitrary HogQL when used
    in experiment query templates via placeholders."""

    def test_timestamp_field_function_call_treated_as_identifier(self):
        """A timestamp_field like 'sleep(3)' must be treated as a field
        reference via ast.Field, not an executable function call."""
        source = ExperimentDataWarehouseNode(
            table_name="some_table",
            timestamp_field="sleep(3)",
            data_warehouse_join_key="distinct_id",
            events_join_key="distinct_id",
        )
        info = MetricSourceInfo.from_source(source)

        # Use the placeholder pattern (the fix) — timestamp_field goes through
        # ast.Field so the parser treats it as a column reference
        result = parse_select(
            "SELECT {ts} AS timestamp FROM events",
            placeholders={"ts": ast.Field(chain=[info.timestamp_field])},
        )
        assert isinstance(result, ast.SelectQuery)

        select_expr = result.select[0]
        if isinstance(select_expr, ast.Alias):
            select_expr = select_expr.expr

        assert isinstance(select_expr, ast.Field), f"Expected ast.Field, got {type(select_expr).__name__}"
        # The malicious string is treated as a literal field name, not parsed as code
        assert select_expr.chain == ["sleep(3)"]

    def test_table_name_injection_treated_as_identifier(self):
        """A table_name with SQL injection payload must be treated as a
        single table identifier via ast.Field."""
        source = ExperimentDataWarehouseNode(
            table_name="events) SELECT 1 --",
            timestamp_field="ts",
            data_warehouse_join_key="distinct_id",
            events_join_key="distinct_id",
        )
        info = MetricSourceInfo.from_source(source)

        result = parse_select(
            "SELECT 1 AS x FROM {tbl}",
            placeholders={"tbl": ast.Field(chain=[info.table_name])},
        )
        assert isinstance(result, ast.SelectQuery)
        assert result.select_from is not None
        assert isinstance(result.select_from.table, ast.Field)
        # The malicious string is a single field chain element, not parsed SQL
        assert result.select_from.table.chain == ["events) SELECT 1 --"]

    def test_timestamp_field_subquery_treated_as_identifier(self):
        """A timestamp_field like '(SELECT currentDatabase())' must be
        treated as a field reference, not a subquery."""
        source = ExperimentDataWarehouseNode(
            table_name="some_table",
            timestamp_field="(SELECT currentDatabase())",
            data_warehouse_join_key="distinct_id",
            events_join_key="distinct_id",
        )
        info = MetricSourceInfo.from_source(source)

        result = parse_select(
            "SELECT {ts} AS timestamp FROM events",
            placeholders={"ts": ast.Field(chain=[info.timestamp_field])},
        )
        assert isinstance(result, ast.SelectQuery)

        select_expr = result.select[0]
        if isinstance(select_expr, ast.Alias):
            select_expr = select_expr.expr

        assert isinstance(select_expr, ast.Field)
        assert select_expr.chain == ["(SELECT currentDatabase())"]
