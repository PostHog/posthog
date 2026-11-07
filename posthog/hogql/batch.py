from collections.abc import Callable, Mapping
from dataclasses import fields

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.parser import parse_select
from posthog.hogql.printer.hogql import HogQLPrinter
from posthog.hogql.visitor import clone_expr

from posthog.dataclasses import frozen


@frozen
class BatchQueryResult:
    columns: tuple[str, ...]
    types: tuple[str, ...]
    rows: tuple[tuple[object, ...], ...]


@frozen
class _CountQuery:
    query_id: str
    query: ast.SelectQuery
    columns: tuple[str, ...]
    count_position: int
    argument: ast.Field | None
    order: str | None

    @property
    def key(self) -> str:
        return repr((self.query.group_by, self.order))


@frozen
class _CountProjection:
    count: _CountQuery
    value_column: int
    presence_column: int | None


@frozen
class BatchStep:
    query_ids: tuple[str, ...]
    query: ast.SelectQuery | ast.SelectSetQuery
    reason: str
    counts: tuple[_CountProjection, ...] = ()

    def split(self, result: BatchQueryResult) -> dict[str, BatchQueryResult]:
        if not self.counts:
            return {self.query_ids[0]: result}
        grouped = bool(self.counts[0].count.query.group_by)
        output: dict[str, BatchQueryResult] = {}
        for projection in self.counts:
            count = projection.count
            positions = [projection.value_column]
            if grouped:
                positions.insert(1 - count.count_position, 0)
            # Nullable counts can be zero in an existing group, so presence is measured separately.
            rows = tuple(
                tuple(row[position] for position in positions)
                for row in result.rows
                if projection.presence_column is None or row[projection.presence_column] != 0
            )
            output[count.query_id] = BatchQueryResult(
                columns=count.columns,
                types=tuple(result.types[position] for position in positions),
                rows=rows,
            )
        return output


@frozen
class BatchPlan:
    steps: tuple[BatchStep, ...]

    def execute(
        self, run_query: Callable[[ast.SelectQuery | ast.SelectSetQuery], BatchQueryResult]
    ) -> dict[str, BatchQueryResult]:
        """The runner must use one team/access context and return complete, untruncated results.

        This experimental interface propagates execution errors without retrying. Callers must
        not wire it into dashboard requests until deadlines and per-chart errors are supported.
        """
        results: dict[str, BatchQueryResult] = {}
        for step in self.steps:
            results.update(step.split(run_query(clone_expr(step.query))))
        return results


class CountBatchPlanner:
    def __init__(self, max_group_size: int = 8) -> None:
        if not 2 <= max_group_size <= 32:
            raise ValueError("max_group_size must be between 2 and 32")
        self.max_group_size = max_group_size

    @staticmethod
    def _conjuncts(expr: ast.Expr | None) -> list[ast.Expr]:
        if expr is None:
            return []
        if isinstance(expr, ast.And):
            return [part for child in expr.exprs for part in CountBatchPlanner._conjuncts(child)]
        return [expr]

    @staticmethod
    def _value(expr: ast.Expr) -> bool:
        if isinstance(expr, ast.Constant):
            return isinstance(expr.value, str | int | float | bool) or expr.value is None
        if isinstance(expr, ast.Tuple | ast.Array):
            return all(isinstance(item, ast.Constant) and CountBatchPlanner._value(item) for item in expr.exprs)
        return False

    @staticmethod
    def _field(expr: ast.Expr) -> bool:
        return isinstance(expr, ast.Field) and (
            expr.chain in (["event"], ["timestamp"], ["distinct_id"], ["uuid"])
            or (len(expr.chain) == 2 and expr.chain[0] == "properties" and isinstance(expr.chain[1], str))
        )

    @classmethod
    def _predicate(cls, expr: ast.Expr) -> bool:
        if isinstance(expr, ast.Constant):
            return isinstance(expr.value, bool)
        if cls._timestamp_bound(expr):
            return True
        if isinstance(expr, ast.And | ast.Or):
            return all(cls._predicate(child) for child in expr.exprs)
        if isinstance(expr, ast.Not):
            return cls._predicate(expr.expr)
        if not isinstance(expr, ast.CompareOperation):
            return False
        return (
            expr.op
            in {
                ast.CompareOperationOp.Eq,
                ast.CompareOperationOp.NotEq,
                ast.CompareOperationOp.Gt,
                ast.CompareOperationOp.GtEq,
                ast.CompareOperationOp.Lt,
                ast.CompareOperationOp.LtEq,
                ast.CompareOperationOp.In,
                ast.CompareOperationOp.NotIn,
            }
            and cls._field(expr.left)
            and isinstance(expr.left, ast.Field)
            and expr.left.chain != ["timestamp"]
            and cls._value(expr.right)
        )

    @staticmethod
    def _timestamp_bound(expr: ast.Expr) -> bool:
        if not (
            isinstance(expr, ast.CompareOperation)
            and isinstance(expr.left, ast.Field)
            and expr.left.chain == ["timestamp"]
            and expr.op
            in {
                ast.CompareOperationOp.Gt,
                ast.CompareOperationOp.GtEq,
                ast.CompareOperationOp.Lt,
                ast.CompareOperationOp.LtEq,
            }
        ):
            return False
        value = expr.right
        if isinstance(value, ast.Call) and value.name == "toDateTime":
            if value != ast.Call(name="toDateTime", args=value.args) or not 1 <= len(value.args) <= 2:
                return False
            return all(isinstance(arg, ast.Constant) and isinstance(arg.value, str) for arg in value.args)
        return isinstance(value, ast.Constant) and isinstance(value.value, str)

    @staticmethod
    def _count_argument(expr: ast.Expr) -> bool:
        return (
            isinstance(expr, ast.Field)
            and all(isinstance(part, str) for part in expr.chain)
            and (len(expr.chain) == 1 or (len(expr.chain) == 2 and expr.chain[0] == "properties"))
            and not str(expr.chain[0]).startswith("__batch_")
        )

    @classmethod
    def _candidate(cls, query_id: str, query: ast.SelectQuery | ast.SelectSetQuery) -> _CountQuery | str:
        if not isinstance(query, ast.SelectQuery):
            return "set operations run separately"
        allowed = {"start", "end", "type", "select", "select_from", "where", "group_by", "order_by"}
        if any(getattr(query, field.name) not in (None, False) for field in fields(query) if field.name not in allowed):
            return "limits, settings, CTEs, and other SELECT clauses run separately"
        if query.select_from != ast.JoinExpr(table=ast.Field(chain=["events"])):
            return "only an unaliased events source without joins or sampling can combine"

        day = ast.Call(name="toDate", args=[ast.Field(chain=["timestamp"])])
        if query.group_by not in (None, [day]):
            return "only totals or GROUP BY toDate(timestamp) can combine"
        grouped = bool(query.group_by)
        if len(query.select) != 1 + int(grouped):
            return "select one count and, for daily queries, the day"
        columns: list[str] = []
        count_position = -1
        argument: ast.Field | None = None
        day_alias: str | None = None
        for index, selected in enumerate(query.select):
            expr = selected.expr if isinstance(selected, ast.Alias) else selected
            alias = selected.alias if isinstance(selected, ast.Alias) else None
            if alias in {"event", "timestamp", "distinct_id", "uuid", "properties"}:
                return "aliases shadowing source columns run separately"
            if (
                isinstance(expr, ast.Call)
                and expr == ast.Call(name="count", args=expr.args)
                and (not expr.args or (len(expr.args) == 1 and cls._count_argument(expr.args[0])))
            ):
                count_position = index
                argument = expr.args[0] if expr.args and isinstance(expr.args[0], ast.Field) else None
                columns.append(alias or HogQLPrinter(context=HogQLContext()).visit(expr))
            elif grouped and expr == day:
                day_alias = alias
                columns.append(alias or "toDate(timestamp)")
            else:
                return "only count(), count(column), and the day expression can combine"
        if (
            count_position < 0
            or (grouped and all((item.expr if isinstance(item, ast.Alias) else item) != day for item in query.select))
            or len(set(columns)) != len(columns)
        ):
            return "select exactly one count and use distinct output names"
        if argument and any(isinstance(item, ast.Alias) and item.alias == argument.chain[0] for item in query.select):
            return "aliases shadowing the counted column run separately"

        order: str | None = None
        if query.order_by:
            if not grouped or len(query.order_by) != 1:
                return "only ordering by the day can combine"
            ordering = query.order_by[0]
            if ordering.with_fill or not (
                ordering.expr == day or (day_alias is not None and ordering.expr == ast.Field(chain=[day_alias]))
            ):
                return "only ordering by the day without WITH FILL can combine"
            order = ordering.order

        if query.where is not None and not cls._predicate(query.where):
            return "unsupported or potentially nondeterministic filter runs separately"
        return _CountQuery(
            query_id=query_id,
            query=query,
            columns=tuple(columns),
            count_position=count_position,
            argument=argument,
            order=order,
        )

    @staticmethod
    def _and(expressions: list[ast.Expr]) -> ast.Expr:
        if not expressions:
            return ast.Constant(value=True)
        return expressions[0] if len(expressions) == 1 else ast.And(exprs=expressions)

    @staticmethod
    def _deduplicate(counts: list[_CountQuery]) -> BatchStep:
        first = counts[0]
        query = clone_expr(first.query)
        grouped = bool(query.group_by)
        day = ast.Call(name="toDate", args=[ast.Field(chain=["timestamp"])])
        selected = query.select[first.count_position]
        aggregate = selected.expr if isinstance(selected, ast.Alias) else selected
        # Keep count(column) intact so ClickHouse can still use its count optimizations.
        query.select = [ast.Alias(alias="__batch_day", expr=day)] if grouped else []
        query.select.append(ast.Alias(alias="__batch_count_0", expr=aggregate))
        if query.order_by:
            query.order_by[0].expr = clone_expr(day)
        return BatchStep(
            query_ids=tuple(count.query_id for count in counts),
            query=query,
            reason="identical count query executed once",
            counts=tuple(
                _CountProjection(count=count, value_column=int(grouped), presence_column=None) for count in counts
            ),
        )

    @staticmethod
    def _combine(counts: list[_CountQuery]) -> BatchStep:
        first = counts[0]
        grouped = bool(first.query.group_by)
        day = ast.Call(name="toDate", args=[ast.Field(chain=["timestamp"])])
        select: list[ast.Expr] = [ast.Alias(alias="__batch_day", expr=day)] if grouped else []
        projections: list[_CountProjection] = []
        aggregates: dict[str, int] = {}

        def aggregate(predicate: ast.Expr) -> int:
            key = repr(predicate)
            if key not in aggregates:
                aggregates[key] = len(select)
                select.append(
                    ast.Alias(
                        alias=f"__batch_count_{len(aggregates) - 1}",
                        expr=ast.Call(name="countIf", args=[clone_expr(predicate)]),
                    )
                )
            return aggregates[key]

        for count in counts:
            predicate = CountBatchPlanner._and(sorted(CountBatchPlanner._conjuncts(count.query.where), key=repr))
            value_predicate = (
                CountBatchPlanner._and([predicate, ast.Call(name="isNotNull", args=[count.argument])])
                if count.argument is not None
                else predicate
            )
            value_column = aggregate(value_predicate)
            projections.append(
                _CountProjection(
                    count=count,
                    value_column=value_column,
                    presence_column=aggregate(predicate) if grouped else None,
                )
            )

        # Keep common range/event predicates visible outside the OR for scan pruning.
        common = [
            expr
            for expr in CountBatchPlanner._conjuncts(first.query.where)
            if all(expr in CountBatchPlanner._conjuncts(count.query.where) for count in counts[1:])
        ]
        residuals: dict[str, ast.Expr] = {}
        for count in counts:
            residual = CountBatchPlanner._and(
                [expr for expr in CountBatchPlanner._conjuncts(count.query.where) if expr not in common]
            )
            residuals[repr(residual)] = residual
        where_parts = list(common)
        if ast.Constant(value=True) not in residuals.values():
            where_parts.append(ast.Or(exprs=list(residuals.values())))
        query = ast.SelectQuery(
            select=select,
            select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
            where=clone_expr(CountBatchPlanner._and(where_parts)) if where_parts else None,
            group_by=[day] if grouped else None,
            order_by=[ast.OrderExpr(expr=day, order=first.query.order_by[0].order)]
            if first.order and first.query.order_by
            else None,
        )
        return BatchStep(
            query_ids=tuple(count.query_id for count in counts),
            query=query,
            reason="shared count scan with per-query filters and deduplicated aggregates",
            counts=tuple(projections),
        )

    def plan(
        self, queries: Mapping[str, str | ast.SelectQuery | ast.SelectSetQuery], *, combine: bool = True
    ) -> BatchPlan:
        steps: list[BatchStep] = []
        groups: dict[str, list[_CountQuery]] = {}
        for query_id, sql in queries.items():
            query = clone_expr(
                parse_select(sql) if isinstance(sql, str) else sql, clear_types=True, clear_locations=True
            )
            candidate = self._candidate(query_id, query) if combine else "combining disabled"
            if isinstance(candidate, str):
                steps.append(BatchStep(query_ids=(query_id,), query=query, reason=candidate))
            else:
                groups.setdefault(candidate.key, []).append(candidate)
        for group in groups.values():
            identical: dict[str, list[_CountQuery]] = {}
            for count in group:
                key = repr((count.argument, sorted(self._conjuncts(count.query.where), key=repr)))
                identical.setdefault(key, []).append(count)
            distinct_counts = list(identical.values())
            for offset in range(0, len(distinct_counts), self.max_group_size):
                counts = [
                    count for copies in distinct_counts[offset : offset + self.max_group_size] for count in copies
                ]
                if len(counts) == 1:
                    count = counts[0]
                    steps.append(
                        BatchStep(query_ids=(count.query_id,), query=count.query, reason="no compatible partner")
                    )
                elif len(distinct_counts[offset : offset + self.max_group_size]) == 1:
                    steps.append(self._deduplicate(counts))
                else:
                    steps.append(self._combine(counts))
        return BatchPlan(steps=tuple(steps))
