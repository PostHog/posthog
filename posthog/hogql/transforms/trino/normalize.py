from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.models import TableNode
from posthog.hogql.database.schema.numbers import NumbersTable
from posthog.hogql.database.trino_unnest_table import TrinoUnnestTable
from posthog.hogql.transforms.trino.any_join import lower_trino_any_joins
from posthog.hogql.transforms.trino.errors import TrinoLoweringError
from posthog.hogql.transforms.trino.query_wrappers import lower_trino_query_wrappers
from posthog.hogql.visitor import CloningVisitor, TraversingVisitor

_MAX_NUMBERS_ROWS = 10_000_000
_EVENT_PROPERTY_BACKED_FIELDS = frozenset(
    {"$session_id", "$window_id", "$group_0", "$group_1", "$group_2", "$group_3", "$group_4"}
)
_EVENT_ELEMENTS_CHAIN_PATTERNS = {
    "elements_chain_texts": r'(?::|")text="(.*?)"',
    "elements_chain_ids": r'(?::|")attr_id="(.*?)"',
    "elements_chain_elements": r"(?:^|;)(a|button|form|input|select|textarea|label)(?:\.|$|:)",
}
_ALL_JOIN_TYPES = {
    "ALL INNER JOIN": "INNER JOIN",
    "LEFT ALL JOIN": "LEFT JOIN",
    "RIGHT ALL JOIN": "RIGHT JOIN",
    "FULL ALL JOIN": "FULL JOIN",
}


def _wrap_unnest_elements(array_expr: ast.Expr, lambda_name: str) -> ast.Call:
    return ast.Call(
        name="arrayMap",
        args=[
            ast.Lambda(
                args=[lambda_name],
                expr=ast.Tuple(exprs=[ast.Field(chain=[lambda_name])]),
            ),
            array_expr,
        ],
    )


class TrinoPhysicalFieldLowerer(CloningVisitor):
    def __init__(self) -> None:
        super().__init__(clear_types=False)

    def visit_field(self, node: ast.Field) -> ast.Expr:
        field_type = node.type
        while isinstance(field_type, ast.FieldAliasType):
            field_type = field_type.type
        table_type = field_type.table_type if isinstance(field_type, ast.FieldType) else None
        while isinstance(table_type, (ast.TableAliasType, ast.ColumnAliasedTableType)):
            table_type = table_type.table_type
        is_events_field = (
            isinstance(table_type, ast.TableType)
            and (table_type.table.name or table_type.table.to_printed_hogql()) == "events"
        )
        if (
            isinstance(field_type, ast.FieldType)
            and field_type.name in _EVENT_PROPERTY_BACKED_FIELDS
            and is_events_field
        ):
            return ast.PropertyAccess(
                start=node.start,
                end=node.end,
                expr=ast.Field(chain=[*node.chain[:-1], "properties"]),
                keys=[field_type.name],
                type=ast.StringType(nullable=True),
            )
        if isinstance(field_type, ast.FieldType) and is_events_field:
            source = ast.Field(chain=[*node.chain[:-1], "elements_chain"])
            if field_type.name == "elements_chain_href":
                return ast.Call(
                    name="ifNull",
                    args=[
                        ast.Call(name="extract", args=[source, ast.Constant(value=r'(?::|")href="(.*?)"')]),
                        ast.Constant(value=""),
                    ],
                )
            pattern = _EVENT_ELEMENTS_CHAIN_PATTERNS.get(field_type.name)
            if pattern is not None:
                return ast.Call(
                    name="arrayDistinct",
                    args=[ast.Call(name="extractAll", args=[source, ast.Constant(value=pattern)])],
                )
        return super().visit_field(node)


class TrinoSemanticCallLowerer(CloningVisitor):
    def __init__(self) -> None:
        super().__init__(clear_types=False)

    def visit_call(self, node: ast.Call) -> ast.Expr:
        lowered = super().visit_call(node)
        if lowered.name.lower() != "not":
            return lowered
        if len(lowered.args) != 1:
            raise TrinoLoweringError("TRINO_NOT_ARGUMENT_COUNT", "not with other than one argument", node)
        return ast.Not(
            start=lowered.start,
            end=lowered.end,
            expr=lowered.args[0],
            type=lowered.type,
        )


class TrinoSelectAliasLowerer(CloningVisitor):
    def __init__(self) -> None:
        super().__init__(clear_types=False)
        self.aliases: dict[str, ast.Expr] = {}
        self.alias_positions: dict[str, int] = {}
        self.expanding: set[str] = set()
        self.in_group_by = False

    def visit_select_query(self, node: ast.SelectQuery) -> ast.SelectQuery:
        outer_aliases = self.aliases
        outer_alias_positions = self.alias_positions
        self.aliases = {expr.alias: expr.expr for expr in node.select if isinstance(expr, ast.Alias)}
        self.alias_positions = {
            expr.alias: index for index, expr in enumerate(node.select, start=1) if isinstance(expr, ast.Alias)
        }
        lowered = super().visit_select_query(node)
        if node.group_by is not None:
            outer_in_group_by = self.in_group_by
            self.in_group_by = True
            try:
                lowered.group_by = [self.visit(expr) for expr in node.group_by]
            finally:
                self.in_group_by = outer_in_group_by
        self.aliases = outer_aliases
        self.alias_positions = outer_alias_positions
        return lowered

    def visit_field(self, node: ast.Field) -> ast.Expr:
        if (
            len(node.chain) == 1
            and isinstance(node.type, ast.FieldAliasType)
            and isinstance(node.chain[0], str)
            and node.chain[0] in self.aliases
            and node.chain[0] not in self.expanding
        ):
            alias = node.chain[0]
            if self.in_group_by:
                return ast.PositionalRef(index=self.alias_positions[alias])
            self.expanding.add(alias)
            try:
                return self.visit(self.aliases[alias])
            finally:
                self.expanding.remove(alias)
        return super().visit_field(node)


class TrinoArrayJoinFunctionLowerer(CloningVisitor):
    def __init__(self, context: HogQLContext) -> None:
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
                table_args=[_wrap_unnest_elements(array_expr, f"{table_name}_value")],
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
            raise TrinoLoweringError("TRINO_ARRAY_JOIN_ARGUMENT_COUNT", "arrayJoin with other than one argument", node)
        if self.context.database is None:
            raise TrinoLoweringError(
                "TRINO_ARRAY_JOIN_DATABASE_REQUIRED", "arrayJoin without a resolved database", node
            )
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
    def __init__(self, context: HogQLContext) -> None:
        self.context = context
        self.unnest_index = 0

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        if node.prewhere is not None:
            node.where = ast.And(exprs=[node.prewhere, node.where]) if node.where is not None else node.prewhere
            node.prewhere = None
        node.settings = None
        self._lower_array_join(node)
        super().visit_select_query(node)

    def _lower_array_join(self, node: ast.SelectQuery) -> None:
        if node.array_join_op is None and not node.array_join_list:
            return
        if node.array_join_op not in {"ARRAY JOIN", "INNER ARRAY JOIN"}:
            raise TrinoLoweringError(
                "TRINO_ARRAY_JOIN_MODE_UNSUPPORTED", node.array_join_op or "ARRAY JOIN without an operation", node
            )
        if node.array_join_list is None or len(node.array_join_list) != 1:
            raise TrinoLoweringError("TRINO_ARRAY_JOIN_MULTIPLE_ARRAYS_UNSUPPORTED", "multiple-array ARRAY JOIN", node)
        array_expr = node.array_join_list[0]
        if not isinstance(array_expr, ast.Alias):
            raise TrinoLoweringError("TRINO_ARRAY_JOIN_ALIAS_REQUIRED", "ARRAY JOIN without an output alias", node)
        if node.select_from is None:
            raise TrinoLoweringError("TRINO_ARRAY_JOIN_RELATION_REQUIRED", "ARRAY JOIN without a FROM relation", node)
        if self.context.database is None:
            raise TrinoLoweringError(
                "TRINO_ARRAY_JOIN_DATABASE_REQUIRED", "ARRAY JOIN without a resolved database", node
            )

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
            table_args=[_wrap_unnest_elements(array_expr.expr, f"{table_name}_value")],
            alias=table_name,
            column_aliases=[array_expr.alias],
        )
        node.array_join_op = None
        node.array_join_list = None

    def visit_join_expr(self, node: ast.JoinExpr) -> None:
        if node.join_type in _ALL_JOIN_TYPES:
            node.join_type = _ALL_JOIN_TYPES[node.join_type]
        table_type = node.type
        while isinstance(table_type, (ast.TableAliasType, ast.ColumnAliasedTableType)):
            table_type = table_type.table_type
        if isinstance(table_type, ast.TableType) and isinstance(table_type.table, NumbersTable):
            if not (
                node.table_args is not None
                and len(node.table_args) == 1
                and isinstance(node.table_args[0], ast.Call)
                and node.table_args[0].name.lower() == "range"
            ):
                node.table_args = [self._lower_numbers_args(node.table_args)]
            if node.column_aliases is None:
                node.column_aliases = ["number"]
        super().visit_join_expr(node)

    def _lower_numbers_args(self, args: list[ast.Expr] | None) -> ast.Call:
        if args is None or len(args) not in {1, 2}:
            raise TrinoLoweringError("TRINO_NUMBERS_ARGUMENT_COUNT", "numbers with other than one or two arguments")
        values: list[int] = []
        for arg in args:
            if not isinstance(arg, ast.Constant) or isinstance(arg.value, bool) or not isinstance(arg.value, int):
                raise TrinoLoweringError(
                    "TRINO_NUMBERS_NON_CONSTANT_ARGUMENT", "numbers requires constant integer arguments", arg
                )
            values.append(arg.value)
        start, count = (0, values[0]) if len(values) == 1 else values
        if count < 0:
            raise TrinoLoweringError("TRINO_NUMBERS_NEGATIVE_ROW_COUNT", "numbers with a negative row count")
        if count > _MAX_NUMBERS_ROWS:
            raise TrinoLoweringError(
                "TRINO_NUMBERS_ROW_LIMIT_EXCEEDED", f"numbers above the {_MAX_NUMBERS_ROWS:,}-row limit"
            )
        return ast.Call(name="range", args=[ast.Constant(value=start), ast.Constant(value=start + count)])


def normalize_trino_ast(node: ast.AST, context: HogQLContext) -> ast.AST:
    lowered = TrinoArrayJoinFunctionLowerer(context).visit(node)
    lowered = TrinoPhysicalFieldLowerer().visit(lowered)
    lowered = TrinoSemanticCallLowerer().visit(lowered)
    lowered = lower_trino_any_joins(lowered)
    lowered = lower_trino_query_wrappers(lowered)
    lowered = TrinoSelectAliasLowerer().visit(lowered)
    TrinoNormalizer(context).visit(lowered)
    return lowered
