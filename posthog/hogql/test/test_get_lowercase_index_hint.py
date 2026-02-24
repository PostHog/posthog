import os
import json
from typing import cast

from posthog.test.base import APIBaseTest, BaseTest, ClickhouseTestMixin, get_index_from_explain

from posthog.schema import (
    DateRange,
    FilterLogicalOperator,
    LogPropertyFilter,
    LogPropertyFilterType,
    LogsQuery,
    PropertyGroupFilter,
    PropertyGroupFilterValue,
    PropertyOperator,
)

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.filters import HogQLFilters
from posthog.hogql.printer import prepare_ast_for_printing, print_prepared_ast
from posthog.hogql.property import _LowercaseIndexRewriter, get_lowercase_index_hint
from posthog.hogql.query import HogQLQueryExecutor
from posthog.hogql.visitor import clear_locations

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import Workload

from products.logs.backend.logs_query_runner import LogsQueryRunner


class TestGetLowercaseIndexHint(BaseTest):
    """Tests for get_lowercase_index_hint and _LowercaseIndexRewriter."""

    maxDiff = None

    def _hint(self, property: LogPropertyFilter) -> ast.Call:
        return cast(ast.Call, clear_locations(get_lowercase_index_hint(property, team=self.team)))

    def _rewrite(self, expr: ast.Expr) -> ast.Expr:
        return clear_locations(_LowercaseIndexRewriter().visit(expr))

    def test_icontains_single_value_log_property(self):
        """ICONTAINS single value on a log property: toString stripped, ILike→Like, lower() wrapped, constant lowered."""
        prop = LogPropertyFilter(
            key="message",
            operator=PropertyOperator.ICONTAINS,
            value="ERROR",
            type=LogPropertyFilterType.LOG,
        )
        result = self._hint(prop)

        # indexHint(lower(message) Like '%error%')
        assert isinstance(result, ast.Call)
        assert result.name == "indexHint"
        assert len(result.args) == 1

        inner = result.args[0]
        assert isinstance(inner, ast.CompareOperation)
        assert inner.op == ast.CompareOperationOp.Like

        # left: lower(message)
        assert isinstance(inner.left, ast.Call)
        assert inner.left.name == "lower"
        assert len(inner.left.args) == 1
        assert isinstance(inner.left.args[0], ast.Field)
        assert inner.left.args[0].chain == ["message"]

        # right: '%error%' (lowered)
        assert isinstance(inner.right, ast.Constant)
        assert inner.right.value == "%error%"

    def test_not_icontains_single_value_log_property(self):
        """NOT_ICONTAINS single value: NotILike→NotLike, lower() wrapped, constant lowered."""
        prop = LogPropertyFilter(
            key="message",
            operator=PropertyOperator.NOT_ICONTAINS,
            value="DEBUG",
            type=LogPropertyFilterType.LOG,
        )
        result = self._hint(prop)

        assert isinstance(result, ast.Call)
        assert result.name == "indexHint"

        inner = result.args[0]
        assert isinstance(inner, ast.CompareOperation)
        assert inner.op == ast.CompareOperationOp.NotLike

        assert isinstance(inner.left, ast.Call)
        assert inner.left.name == "lower"
        assert isinstance(inner.left.args[0], ast.Field)
        assert inner.left.args[0].chain == ["message"]

        assert isinstance(inner.right, ast.Constant)
        assert inner.right.value == "%debug%"

    def test_icontains_multi_value_log_property(self):
        """ICONTAINS with multiple values uses multiSearchAnyCaseInsensitive → multiSearchAny(lower(...), lowered)."""
        prop = LogPropertyFilter(
            key="message",
            operator=PropertyOperator.ICONTAINS,
            value=["ERROR", "WARNING"],
            type=LogPropertyFilterType.LOG,
        )
        result = self._hint(prop)

        assert isinstance(result, ast.Call)
        assert result.name == "indexHint"

        # The inner expr should be: multiSearchAny(lower(message), ['error', 'warning']) > 0
        inner = result.args[0]
        assert isinstance(inner, ast.CompareOperation)
        assert inner.op == ast.CompareOperationOp.Gt

        search_call = inner.left
        assert isinstance(search_call, ast.Call)
        assert search_call.name == "multiSearchAny"
        assert len(search_call.args) == 2

        # haystack: lower(message)
        haystack = search_call.args[0]
        assert isinstance(haystack, ast.Call)
        assert haystack.name == "lower"
        assert isinstance(haystack.args[0], ast.Field)
        assert haystack.args[0].chain == ["message"]

        # needles: ['error', 'warning']
        needles = search_call.args[1]
        assert isinstance(needles, ast.Array)
        assert len(needles.exprs) == 2
        assert cast(ast.Constant, needles.exprs[0]).value == "error"
        assert cast(ast.Constant, needles.exprs[1]).value == "warning"

        # right side of >: 0
        assert isinstance(inner.right, ast.Constant)
        assert inner.right.value == 0

    def test_icontains_mixed_case_preserved_as_lower(self):
        """Mixed-case value is lowered in the hint."""
        prop = LogPropertyFilter(
            key="message",
            operator=PropertyOperator.ICONTAINS,
            value="FaTaL Error",
            type=LogPropertyFilterType.LOG,
        )
        result = self._hint(prop)

        inner = cast(ast.CompareOperation, result.args[0])
        assert cast(ast.Constant, inner.right).value == "%fatal error%"

    def test_icontains_multi_with_mixed_case_needles(self):
        """Multiple mixed-case needles are all lowered."""
        prop = LogPropertyFilter(
            key="message",
            operator=PropertyOperator.ICONTAINS,
            value=["FoO", "BaR", "BAZ"],
            type=LogPropertyFilterType.LOG,
        )
        result = self._hint(prop)

        inner = cast(ast.CompareOperation, result.args[0])
        search_call = cast(ast.Call, inner.left)
        needles = cast(ast.Array, search_call.args[1])
        assert [cast(ast.Constant, e).value for e in needles.exprs] == ["foo", "bar", "baz"]

    def test_icontains_multi_operator_single_value(self):
        """ICONTAINS_MULTI with a single string value uses multiSearch path."""
        prop = LogPropertyFilter(
            key="message",
            operator=PropertyOperator.ICONTAINS_MULTI,
            value="Err",
            type=LogPropertyFilterType.LOG,
        )
        result = self._hint(prop)

        assert result.name == "indexHint"
        inner = result.args[0]
        assert isinstance(inner, ast.CompareOperation)
        assert inner.op == ast.CompareOperationOp.Gt

        search_call = inner.left
        assert isinstance(search_call, ast.Call)
        assert search_call.name == "multiSearchAny"
        needles = search_call.args[1]
        assert isinstance(needles, ast.Array)
        assert [cast(ast.Constant, e).value for e in needles.exprs] == ["err"]


class TestGetLowercaseIndexHintClickhouse(ClickhouseTestMixin, APIBaseTest):
    CLASS_DATA_LEVEL_SETUP = True

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        schema_path = os.path.join(
            os.path.dirname(__file__), "../../../products/logs/backend/test/test_logs_schema.sql"
        )
        with open(schema_path) as f:
            schema_sql = f.read()
        for sql in schema_sql.split(";"):
            if not sql.strip():
                continue
            sync_execute(sql)
        # Insert a single row so EXPLAIN has data to plan against
        logs_path = os.path.join(os.path.dirname(__file__), "../../../products/logs/backend/test/test_logs.jsonnd")
        with open(logs_path) as f:
            log_item = json.loads(f.readline())
            log_item["team_id"] = cls.team.id
            sync_execute(f"INSERT INTO logs FORMAT JSONEachRow\n{json.dumps(log_item)}")

    def test_index_hint_uses_ngram_index(self):
        """The index hint on a message ICONTAINS filter should cause ClickHouse to use the idx_body_ngram3 index."""
        query = LogsQuery(
            kind="LogsQuery",
            dateRange=DateRange(date_from="2025-12-16T09:00:00Z", date_to="2025-12-16T10:00:00Z"),
            serviceNames=[],
            severityLevels=[],
            filterGroup=PropertyGroupFilter(
                type=FilterLogicalOperator.AND_,
                values=[
                    PropertyGroupFilterValue(
                        type=FilterLogicalOperator.AND_,
                        values=[
                            LogPropertyFilter(
                                key="message",
                                value="test",
                                operator=PropertyOperator.ICONTAINS,
                                type=LogPropertyFilterType.LOG,
                            ),
                        ],
                    )
                ],
            ),
        )
        runner = LogsQueryRunner(query=query, team=self.team)
        executor = HogQLQueryExecutor(
            query_type="LogsQuery",
            query=runner.to_query(),
            modifiers=runner.modifiers,
            team=runner.team,
            workload=Workload.LOGS,
            timings=runner.timings,
            limit_context=runner.limit_context,
            filters=HogQLFilters(dateRange=runner.query.dateRange),
            settings=runner.settings,
        )
        clickhouse_sql, _ = executor.generate_clickhouse_sql()
        index_info = get_index_from_explain(clickhouse_sql, "idx_body_ngram3")
        assert index_info is not None, (
            f"Expected idx_body_ngram3 to be used in EXPLAIN output for query:\n{clickhouse_sql}"
        )

    def test_index_hint_prints_without_ifnull(self):
        """The printed ClickHouse SQL inside indexHint must not contain ifNull — it defeats index usage."""
        hint_node = get_lowercase_index_hint(
            LogPropertyFilter(
                key="message",
                operator=PropertyOperator.ICONTAINS,
                value="test",
                type=LogPropertyFilterType.LOG,
            ),
            team=self.team,
        )
        select = ast.SelectQuery(
            select=[hint_node],
            select_from=ast.JoinExpr(table=ast.Field(chain=["logs"])),
        )
        context = HogQLContext(team_id=self.team.pk, enable_select_queries=True)
        prepared = cast(
            ast.SelectQuery,
            prepare_ast_for_printing(select, context=context, dialect="clickhouse"),
        )
        sql = print_prepared_ast(prepared.select[0], context=context, dialect="clickhouse", stack=[prepared])
        assert "ifNull" not in sql, f"indexHint should not contain ifNull, got: {sql}"
        assert "indexHint" in sql
        assert "lower" in sql
