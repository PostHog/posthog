"""Execution-only scan narrowing for last-row threshold alerts.

Only recognize bucket-local, bounded hourly event aggregations. An arbitrary SQL
LIMIT does not reduce aggregation reads, and pushing time predicates into arbitrary
SQL can change its answer. Unsupported shapes retain their original execution.
"""

from copy import deepcopy
from dataclasses import fields

from posthog.hogql import ast
from posthog.hogql.constants import MAX_SELECT_RETURNED_ROWS, LimitContext, get_default_limit_for_context
from posthog.hogql.errors import BaseHogQLError
from posthog.hogql.parser import parse_select


class HourlyLastRowQuery:
    def __init__(self, query: ast.SelectQuery, column: str) -> None:
        self.query = query
        self.column = column

    @staticmethod
    def _plain_call(expr: ast.Expr, name: str) -> bool:
        return (
            isinstance(expr, ast.Call)
            and expr.name == name
            and not any((expr.params, expr.distinct, expr.within_group, expr.order_by, expr.filter_expr))
        )

    @staticmethod
    def _timestamp(expr: ast.Expr) -> bool:
        return isinstance(expr, ast.Field) and expr.chain == ["timestamp"]

    def _bucket(self, expr: ast.Expr) -> bool:
        return (
            isinstance(expr, ast.Call)
            and self._plain_call(expr, "toStartOfHour")
            and len(expr.args) == 1
            and self._timestamp(expr.args[0])
        )

    def _end(self, expr: ast.Expr) -> bool:
        return (
            self._plain_call(expr, "toStartOfHour")
            and isinstance(expr, ast.Call)
            and len(expr.args) == 1
            and self._plain_call(expr.args[0], "now")
            and isinstance(expr.args[0], ast.Call)
            and not expr.args[0].args
        )

    def _row_local(self, expr: ast.Expr) -> bool:
        if isinstance(expr, ast.Constant):
            return True
        if isinstance(expr, ast.Field):
            return bool(expr.chain) and expr.chain[0] in (
                "timestamp",
                "event",
                "distinct_id",
                "person_id",
                "properties",
            )
        if isinstance(expr, ast.CompareOperation):
            return (
                expr.op
                in (
                    ast.CompareOperationOp.Eq,
                    ast.CompareOperationOp.NotEq,
                    ast.CompareOperationOp.Gt,
                    ast.CompareOperationOp.GtEq,
                    ast.CompareOperationOp.Lt,
                    ast.CompareOperationOp.LtEq,
                    ast.CompareOperationOp.In,
                    ast.CompareOperationOp.NotIn,
                )
                and self._row_local(expr.left)
                and self._row_local(expr.right)
            )
        if isinstance(expr, ast.And | ast.Or):
            return all(self._row_local(part) for part in expr.exprs)
        if isinstance(expr, ast.Not):
            return self._row_local(expr.expr)
        if isinstance(expr, ast.Tuple):
            return all(self._row_local(part) for part in expr.exprs)
        if self._end(expr):
            return True
        if isinstance(expr, ast.ArithmeticOperation) and expr.op == ast.ArithmeticOperationOp.Sub:
            return self._end(expr.left) and self._hours(expr.right) is not None
        return False

    def _hours(self, expr: ast.Expr) -> int | None:
        if (
            isinstance(expr, ast.Call)
            and self._plain_call(expr, "toIntervalHour")
            and len(expr.args) == 1
            and isinstance(expr.args[0], ast.Constant)
            and type(expr.args[0].value) is int
        ):
            return expr.args[0].value
        return None

    def _aggregate(self, expr: ast.Expr) -> bool:
        if isinstance(expr, ast.ArithmeticOperation) and expr.op in (
            ast.ArithmeticOperationOp.Add,
            ast.ArithmeticOperationOp.Sub,
        ):
            return self._aggregate(expr.left) and self._aggregate(expr.right)
        if not isinstance(expr, ast.Call) or not self._plain_call(expr, expr.name):
            return False
        if expr.name == "count":
            return not expr.args
        if expr.name == "countIf":
            return len(expr.args) == 1 and self._row_local(expr.args[0])
        if expr.name in ("uniq", "uniqExact", "uniqIf", "uniqExactIf"):
            return len(expr.args) == (2 if expr.name.endswith("If") else 1) and all(
                self._row_local(arg) for arg in expr.args
            )
        return False

    def _eligible_shape(self) -> bool:
        query = self.query
        # Fail closed for new clauses, as well as windows, joins, fill,
        # CTEs and HAVING. Those can make the last row depend on earlier buckets.
        allowed = {"start", "end", "type", "select", "select_from", "where", "group_by", "order_by", "limit"}
        if any(getattr(query, field.name) for field in fields(query) if field.name not in allowed):
            return False
        source = query.select_from
        if not source or not isinstance(source.table, ast.Field) or source.table.chain != ["events"]:
            return False
        if any(
            getattr(source, field.name)
            for field in fields(source)
            if field.name not in {"start", "end", "type", "table"}
        ):
            return False
        if len(query.select) != 2 or not all(isinstance(expr, ast.Alias) for expr in query.select):
            return False
        bucket, value = query.select
        assert isinstance(bucket, ast.Alias) and isinstance(value, ast.Alias)
        reserved = {"timestamp", "event", "distinct_id", "person_id", "properties", "events"}
        if bucket.alias in reserved or value.alias in reserved or bucket.alias == value.alias:
            return False
        if not self._bucket(bucket.expr) or value.alias != self.column or not self._aggregate(value.expr):
            return False
        if not query.group_by or len(query.group_by) != 1:
            return False
        group = query.group_by[0]
        if not isinstance(group, ast.Field) or group.chain != [bucket.alias]:
            return False
        if not query.order_by or len(query.order_by) != 1:
            return False
        order = query.order_by[0]
        if (
            order.order != "ASC"
            or order.with_fill
            or not isinstance(order.expr, ast.Field)
            or order.expr.chain != [bucket.alias]
        ):
            return False
        return True

    def optimize(self) -> ast.SelectQuery | None:
        query = self.query
        if not self._eligible_shape():
            return None
        if not isinstance(query.where, ast.And) or not self._row_local(query.where):
            return None
        row_limit = get_default_limit_for_context(LimitContext.QUERY_ASYNC)
        if query.limit is not None:
            if (
                not isinstance(query.limit, ast.Constant)
                or type(query.limit.value) is not int
                or query.limit.value <= 0
            ):
                return None
            row_limit = min(query.limit.value, MAX_SELECT_RETURNED_ROWS)
        has_start = has_end = False
        for predicate in query.where.exprs:
            if not isinstance(predicate, ast.CompareOperation) or not self._timestamp(predicate.left):
                continue
            if predicate.op == ast.CompareOperationOp.Lt and self._end(predicate.right):
                has_end = True
            lower = predicate.right
            if (
                predicate.op == ast.CompareOperationOp.GtEq
                and isinstance(lower, ast.ArithmeticOperation)
                and lower.op == ast.ArithmeticOperationOp.Sub
                and self._end(lower.left)
            ):
                hours = self._hours(lower.right)
                # Preserve the original result even under the runner's default
                # pagination (which is smaller than the hard cap). A redundant
                # explicit LIMIT is also safe. Reserve timezone offset headroom.
                has_start |= hours is not None and 2 < hours < row_limit - 48
        if not has_start or not has_end:
            return None
        query.where.exprs.append(
            ast.CompareOperation(
                left=ast.Field(chain=["timestamp"]),
                op=ast.CompareOperationOp.GtEq,
                right=ast.Call(
                    name="toStartOfHour",
                    args=[
                        ast.ArithmeticOperation(
                            left=ast.Call(name="toStartOfHour", args=[ast.Call(name="now", args=[])]),
                            op=ast.ArithmeticOperationOp.Sub,
                            right=ast.Call(name="toIntervalHour", args=[ast.Constant(value=2)]),
                        )
                    ],
                ),
            )
        )
        return query


def optimize_last_row_query(query: object, *, column: str | None) -> dict | None:
    if not isinstance(query, dict) or not column:
        return None
    source = query.get("source") if query.get("kind") == "DataVisualizationNode" else query
    if not isinstance(source, dict) or source.get("kind") != "HogQLQuery" or not isinstance(source.get("query"), str):
        return None
    if source.get("connectionId") or source.get("sendRawQuery") or source.get("explain"):
        return None
    try:
        parsed = parse_select(source["query"])
        if not isinstance(parsed, ast.SelectQuery):
            return None
        optimized = HourlyLastRowQuery(parsed, column).optimize()
        if optimized is None:
            return None
        result = deepcopy(query)
        target = result["source"] if query.get("kind") == "DataVisualizationNode" else result
        target["query"] = optimized.to_hogql()
        return result
    except BaseHogQLError:
        # Let the normal query execution report invalid or unsupported HogQL.
        return None
