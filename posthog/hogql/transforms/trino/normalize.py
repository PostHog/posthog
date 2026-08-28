from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.models import TableNode
from posthog.hogql.database.schema.numbers import NumbersTable
from posthog.hogql.database.trino_unnest_table import TrinoUnnestTable
from posthog.hogql.errors import QueryError
from posthog.hogql.transforms.trino.query_wrappers import lower_trino_query_wrappers
from posthog.hogql.visitor import CloningVisitor, TraversingVisitor

_MAX_NUMBERS_ROWS = 10_000_000


class TrinoArrayJoinFunctionLowerer(CloningVisitor):
    def __init__(self, context: HogQLContext):
        super().__init__(clear_types=False)
        self.context = context
        self.pending_unnests: list[tuple[str, str, ast.Expr]] = []
        self.unnest_index = 0

    def visit_select_query(self, node: ast.SelectQuery) -> ast.SelectQuery:
        outer_pending = self.pending_unnests
        self.pending_unnests = []
        lowered = super().visit_select_query(node)
        pending = self.pending_unnests
        self.pending_unnests = outer_pending
        for table_name, output_name, array_expr in pending:
            join = ast.JoinExpr(
                join_type="CROSS JOIN" if lowered.select_from is not None else None,
                table=ast.Field(chain=[table_name]),
                table_args=[array_expr],
                alias=table_name,
                column_aliases=[output_name],
            )
            if lowered.select_from is None:
                lowered.select_from = join
            else:
                final_join = lowered.select_from
                while final_join.next_join is not None:
                    final_join = final_join.next_join
                final_join.next_join = join
        return lowered

    def visit_call(self, node: ast.Call) -> ast.Expr:
        if node.name.lower() != "arrayjoin":
            return super().visit_call(node)
        if len(node.args) != 1:
            raise QueryError("arrayJoin expects exactly one argument in Trino mode.")
        if self.context.database is None:
            raise QueryError("arrayJoin lowering requires a resolved database in Trino mode.")
        table_name = f"__trino_array_function_{self.unnest_index}"
        output_name = f"value_{self.unnest_index}"
        self.unnest_index += 1
        self.context.database.tables.add_child(
            TableNode(name=table_name, table=TrinoUnnestTable(name=table_name)),
            table_conflict_mode="override",
        )
        self.pending_unnests.append((table_name, output_name, self.visit(node.args[0])))
        return ast.Field(chain=[output_name], start=node.start, end=node.end)


class TrinoNormalizer(TraversingVisitor):
    def __init__(self, context: HogQLContext):
        self.context = context
        self.unnest_index = 0

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        if node.prewhere is not None:
            node.where = ast.And(exprs=[node.prewhere, node.where]) if node.where is not None else node.prewhere
            node.prewhere = None
        self._lower_array_join(node)
        super().visit_select_query(node)

    def _lower_array_join(self, node: ast.SelectQuery) -> None:
        if node.array_join_op is None and not node.array_join_list:
            return
        if node.array_join_op not in {"ARRAY JOIN", "INNER ARRAY JOIN"}:
            raise QueryError("Only single INNER ARRAY JOIN is supported in Trino mode.")
        if node.array_join_list is None or len(node.array_join_list) != 1:
            raise QueryError("Only single-array ARRAY JOIN is supported in Trino mode.")
        array_expr = node.array_join_list[0]
        if not isinstance(array_expr, ast.Alias):
            raise QueryError("ARRAY JOIN requires an explicit output alias in Trino mode.")
        if node.select_from is None:
            raise QueryError("ARRAY JOIN requires a FROM relation in Trino mode.")
        if self.context.database is None:
            raise QueryError("ARRAY JOIN lowering requires a resolved database in Trino mode.")

        table_name = f"__trino_unnest_{self.unnest_index}"
        self.unnest_index += 1
        self.context.database.tables.add_child(
            TableNode(name=table_name, table=TrinoUnnestTable(name=table_name)),
            table_conflict_mode="override",
        )
        final_join = node.select_from
        while final_join.next_join is not None:
            final_join = final_join.next_join
        final_join.next_join = ast.JoinExpr(
            join_type="CROSS JOIN",
            table=ast.Field(chain=[table_name]),
            table_args=[array_expr.expr],
            alias=table_name,
            column_aliases=[array_expr.alias],
        )
        node.array_join_op = None
        node.array_join_list = None

    def visit_join_expr(self, node: ast.JoinExpr) -> None:
        table_type = node.type
        while isinstance(table_type, (ast.TableAliasType, ast.ColumnAliasedTableType)):
            table_type = table_type.table_type
        if isinstance(table_type, ast.TableType) and isinstance(table_type.table, NumbersTable):
            node.table_args = [self._lower_numbers_args(node.table_args)]
            if node.column_aliases is None:
                node.column_aliases = ["number"]
        super().visit_join_expr(node)

    def _lower_numbers_args(self, args: list[ast.Expr] | None) -> ast.Call:
        if args is None or len(args) not in {1, 2}:
            raise QueryError("numbers expects one or two arguments in Trino mode.")
        values: list[int] = []
        for arg in args:
            if not isinstance(arg, ast.Constant) or isinstance(arg.value, bool) or not isinstance(arg.value, int):
                raise QueryError("numbers requires constant integer arguments in Trino mode.")
            values.append(arg.value)
        start, count = (0, values[0]) if len(values) == 1 else values
        if count < 0:
            raise QueryError("numbers requires a non-negative row count in Trino mode.")
        if count > _MAX_NUMBERS_ROWS:
            raise QueryError(f"numbers is limited to {_MAX_NUMBERS_ROWS:,} rows in Trino mode.")
        return ast.Call(name="range", args=[ast.Constant(value=start), ast.Constant(value=start + count)])


def normalize_trino_ast(node: ast.AST, context: HogQLContext) -> ast.AST:
    lowered = TrinoArrayJoinFunctionLowerer(context).visit(node)
    lowered = lower_trino_query_wrappers(lowered)
    TrinoNormalizer(context).visit(lowered)
    return lowered
