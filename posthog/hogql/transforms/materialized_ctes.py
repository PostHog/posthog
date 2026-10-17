from collections import defaultdict

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.schema.events import EventsTable
from posthog.hogql.visitor import TraversingVisitor

from posthog.dataclasses import frozen


@frozen
class _TimestampBounds:
    lower: bool = False
    upper: bool = False


class CTEReferences(TraversingVisitor):
    def __init__(self) -> None:
        super().__init__()
        self.definitions: dict[int, ast.CTE] = {}
        self.consumers: dict[int, list[ast.SelectQuery]] = defaultdict(list)
        self.selects: list[ast.SelectQuery] = []
        self.set_depth = 0
        self.unshared: set[int] = set()

    def visit_field(self, node: ast.Field) -> None:
        pass

    def visit_cte(self, node: ast.CTE) -> None:
        if node.expr.type is not None:
            self.definitions[id(node.expr.type)] = node
            if self.set_depth:
                self.unshared.add(id(node.expr.type))
        super().visit_cte(node)

    def visit_select_set_query(self, node: ast.SelectSetQuery) -> None:
        # ClickHouse expands WITH independently across set operands, including materialization hints.
        self.set_depth += 1
        super().visit_select_set_query(node)
        self.set_depth -= 1

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        self.selects.append(node)
        super().visit_select_query(node)
        self.selects.pop()

    def visit_join_expr(self, node: ast.JoinExpr) -> None:
        table_type = node.table.type if node.table is not None else None
        if isinstance(table_type, ast.CTETableAliasType):
            table_type = table_type.cte_table_type
        if isinstance(table_type, ast.CTETableType) and self.selects:
            self.consumers[id(table_type.select_query_type)].append(self.selects[-1])
        super().visit_join_expr(node)


class _DeterministicEventsAggregate(TraversingVisitor):
    _AGGREGATES = frozenset({"count", "countIf", "min", "max", "uniqExact"})
    _CALLS = _AGGREGATES | frozenset(
        {
            "toDateTime",
            "toDate",
            "toStartOfDay",
            "toStartOfWeek",
            "toStartOfMonth",
            "toStartOfHour",
            "toStartOfMinute",
            "toTimeZone",
        }
    )

    def __init__(self, query: ast.SelectQuery, context: HogQLContext) -> None:
        super().__init__()
        self.query = query
        self.context = context
        self.safe = True
        self.aggregate = False

    def visit_field(self, node: ast.Field) -> None:
        field_type = node.type
        if not isinstance(field_type, ast.FieldType):
            self.safe = False
            return
        table_type = field_type.table_type
        if table_type is self.query.type:
            return
        if not isinstance(table_type, ast.BaseTableType) or not isinstance(
            table_type.resolve_database_table(self.context), EventsTable
        ):
            self.safe = False
            return
        # A correlated events reference also names EventsTable: require the same resolved scope.
        source = self.query.select_from
        if source is None or source.table is None or table_type is not source.table.type:
            self.safe = False

    def visit_call(self, node: ast.Call) -> None:
        if node.name not in self._CALLS or node.params or node.distinct:
            self.safe = False
        if node.name in self._AGGREGATES:
            self.aggregate = True
        super().visit_call(node)

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        self.safe = False

    def visit_select_set_query(self, node: ast.SelectSetQuery) -> None:
        self.safe = False

    def visit_window_function(self, node: ast.WindowFunction) -> None:
        self.safe = False

    @staticmethod
    def _strip_alias(node: ast.Expr) -> ast.Expr:
        while isinstance(node, ast.Alias):
            node = node.expr
        return node

    @classmethod
    def _literal_date(cls, node: ast.Expr) -> bool:
        node = cls._strip_alias(node)
        return (
            isinstance(node, ast.Constant)
            and node.value is not None
            or (
                isinstance(node, ast.Call)
                and node.name in {"toDate", "toDateTime"}
                and bool(node.args)
                and all(isinstance(arg, ast.Constant) and arg.value is not None for arg in node.args)
            )
        )

    def _timestamp(self, node: ast.Expr) -> bool:
        node = self._strip_alias(node)
        source = self.query.select_from
        return (
            isinstance(node, ast.Field)
            and isinstance(node.type, ast.FieldType)
            and node.type.name == "timestamp"
            and source is not None
            and source.table is not None
            and node.type.table_type is source.table.type
        )

    def _bounds(self, node: ast.Expr | None) -> _TimestampBounds:
        if isinstance(node, ast.And):
            bounds = [self._bounds(expr) for expr in node.exprs]
            return _TimestampBounds(
                lower=any(bound.lower for bound in bounds), upper=any(bound.upper for bound in bounds)
            )
        if isinstance(node, ast.BetweenExpr) and not node.negated and self._timestamp(node.expr):
            return _TimestampBounds(lower=self._literal_date(node.low), upper=self._literal_date(node.high))
        if isinstance(node, ast.CompareOperation):
            op = node.op
            if self._timestamp(node.right) and self._literal_date(node.left):
                op = {
                    ast.CompareOperationOp.Gt: ast.CompareOperationOp.Lt,
                    ast.CompareOperationOp.GtEq: ast.CompareOperationOp.LtEq,
                    ast.CompareOperationOp.Lt: ast.CompareOperationOp.Gt,
                    ast.CompareOperationOp.LtEq: ast.CompareOperationOp.GtEq,
                }.get(op, op)
            elif not (self._timestamp(node.left) and self._literal_date(node.right)):
                return _TimestampBounds()
            return _TimestampBounds(
                lower=op in {ast.CompareOperationOp.Gt, ast.CompareOperationOp.GtEq, ast.CompareOperationOp.Eq},
                upper=op in {ast.CompareOperationOp.Lt, ast.CompareOperationOp.LtEq, ast.CompareOperationOp.Eq},
            )
        return _TimestampBounds()

    def eligible(self) -> bool:
        query = self.query
        source = query.select_from
        bounds = self._bounds(ast.And(exprs=[expr for expr in (query.where, query.prewhere) if expr is not None]))
        if (
            source is None
            or source.table is None
            or source.next_join is not None
            or source.table_args
            or source.sample is not None
            or not isinstance(source.table.type, ast.BaseTableType)
            or not isinstance(source.table.type.resolve_database_table(self.context), EventsTable)
            or query.ctes
            or query.limit is not None
            or query.limit_by is not None
            or query.offset is not None
            or query.order_by
            or query.array_join_list
            or query.window_exprs
            or query.qualify
            or query.settings
            or not bounds.lower
            or not bounds.upper
        ):
            return False
        for expr in [*query.select, *(query.group_by or []), query.where, query.prewhere, query.having]:
            self.visit(expr)
        return self.safe and self.aggregate


def materialize_repeated_ctes(node: ast.AST, context: HogQLContext) -> None:
    references = CTEReferences()
    references.visit(node)
    for type_id, cte in references.definitions.items():
        consumers = references.consumers[type_id]
        if (
            type_id in references.unshared
            or cte.materialized is not None
            or cte.recursive
            or cte.columns
            or cte.using_key
            or cte.cte_type != "subquery"
            or not isinstance(cte.expr, ast.SelectQuery)
            or len(consumers) < 2
            or len({id(consumer) for consumer in consumers}) != 1
        ):
            continue
        # Consumer predicates may benefit more from pushdown than from sharing the entire aggregate.
        filtered = False
        for consumer in consumers:
            if consumer.where or consumer.prewhere:
                filtered = True
            join = consumer.select_from.next_join if consumer.select_from else None
            while join is not None:
                if join.join_type != "CROSS JOIN" or join.constraint is not None:
                    filtered = True
                join = join.next_join
        if filtered:
            continue
        if _DeterministicEventsAggregate(cte.expr, context).eligible():
            cte.materialized = True
