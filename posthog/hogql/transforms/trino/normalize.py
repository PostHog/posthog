from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.models import DatabaseField, ExpressionField
from posthog.hogql.database.schema.numbers import NumbersTable
from posthog.hogql.database.trino_unnest_table import TRINO_UNNEST_TABLE_NAME
from posthog.hogql.transforms.trino.any_join import lower_trino_any_joins
from posthog.hogql.transforms.trino.errors import TrinoLoweringError
from posthog.hogql.transforms.trino.expressions import expression_key, positional_index
from posthog.hogql.transforms.trino.query_wrappers import lower_trino_query_wrappers
from posthog.hogql.visitor import CloningVisitor, TraversingVisitor, clone_expr

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
    def __init__(self, context: HogQLContext) -> None:
        super().__init__(clear_types=False)
        self.context = context

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
        if isinstance(field_type, ast.FieldType) and isinstance(table_type, ast.TableType):
            database_field = field_type.resolve_database_field(self.context)
            if isinstance(database_field, DatabaseField) and database_field.name != field_type.name:
                lowered = super().visit_field(node)
                lowered.chain[-1] = database_field.name
                return lowered
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


class TrinoScalarCTELowerer(CloningVisitor):
    def __init__(self) -> None:
        super().__init__(clear_types=False)
        self.scalar_ctes: dict[str, ast.Expr] = {}

    def visit_select_query(self, node: ast.SelectQuery) -> ast.SelectQuery:
        outer_scalar_ctes = self.scalar_ctes
        self.scalar_ctes = dict(outer_scalar_ctes)
        try:
            for name, cte in (node.ctes or {}).items():
                if cte.cte_type == "column":
                    self.scalar_ctes[name] = self.visit(cte.expr)
            lowered = super().visit_select_query(node)
            if lowered.ctes:
                lowered.ctes = {name: cte for name, cte in lowered.ctes.items() if cte.cte_type == "subquery"}
                if not lowered.ctes:
                    lowered.ctes = None
            return lowered
        finally:
            self.scalar_ctes = outer_scalar_ctes

    def visit_field(self, node: ast.Field) -> ast.Expr:
        if len(node.chain) == 1 and isinstance(node.chain[0], str) and node.chain[0] in self.scalar_ctes:
            return clone_expr(self.scalar_ctes[node.chain[0]], clear_types=False)
        return super().visit_field(node)


class TrinoSelectAliasLowerer(CloningVisitor):
    def __init__(self) -> None:
        super().__init__(clear_types=False)
        self.aliases: dict[str, ast.Expr] = {}
        self.expanding: set[str] = set()

    def visit_select_query(self, node: ast.SelectQuery) -> ast.SelectQuery:
        outer_aliases = self.aliases
        self.aliases = {expr.alias: expr.expr for expr in node.select if isinstance(expr, ast.Alias)}
        lowered = super().visit_select_query(node)
        if node.group_by is not None and lowered.group_by is not None and lowered.group_by_mode is None:
            projections = [expression_key(expr) for expr in lowered.select]
            # Separate parameter occurrences are not identical grouping expressions in Trino.
            for index, expr in enumerate(lowered.group_by):
                if positional_index(node.group_by[index]) is not None:
                    continue
                key = expression_key(expr)
                if key in projections:
                    lowered.group_by[index] = ast.PositionalRef(index=projections.index(key) + 1)
        if node.order_by is not None and lowered.order_by is not None:
            alias_positions = {
                expr.alias: index + 1 for index, expr in enumerate(node.select) if isinstance(expr, ast.Alias)
            }
            for original, order in zip(node.order_by, lowered.order_by, strict=True):
                expr = original.expr
                while isinstance(expr, ast.Alias) and expr.hidden:
                    expr = expr.expr
                if (
                    isinstance(expr, ast.Field)
                    and isinstance(expr.type, ast.FieldAliasType)
                    and len(expr.chain) == 1
                    and isinstance(expr.chain[0], str)
                    and (position := alias_positions.get(expr.chain[0])) is not None
                ):
                    order.expr = ast.PositionalRef(index=position)
        self.aliases = outer_aliases
        return lowered

    def visit_join_expr(self, node: ast.JoinExpr) -> ast.JoinExpr:
        outer_aliases = self.aliases
        next_join = node.next_join
        node.next_join = None
        self.aliases = {}
        try:
            lowered = super().visit_join_expr(node)
        finally:
            self.aliases = outer_aliases
            node.next_join = next_join
        if node.table_args is not None:
            lowered.table_args = []
            for argument in node.table_args:
                while isinstance(argument, ast.Alias) and argument.hidden:
                    argument = argument.expr
                lowered.table_args.append(self.visit(argument))
        lowered.next_join = self.visit(next_join) if next_join is not None else None
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
            self.expanding.add(alias)
            try:
                return self.visit(self.aliases[alias])
            finally:
                self.expanding.remove(alias)
        return super().visit_field(node)


class TrinoPhysicalProjectionAliasLowerer(CloningVisitor):
    def __init__(self, context: HogQLContext) -> None:
        super().__init__(clear_types=False)
        self.context = context

    def visit_select_query(self, node: ast.SelectQuery) -> ast.SelectQuery:
        lowered = super().visit_select_query(node)
        for projection in lowered.select:
            if not isinstance(projection, ast.Alias) or not projection.hidden:
                continue
            expression = projection.expr
            while isinstance(expression, ast.Alias) and expression.hidden:
                expression = expression.expr
            field_type = expression.type
            while isinstance(field_type, ast.FieldAliasType):
                field_type = field_type.type
            if not isinstance(field_type, ast.FieldType):
                if self._selects_expression_field(lowered.select_from, projection.alias):
                    projection.hidden = False
                continue
            database_field = field_type.resolve_database_field(self.context)
            if isinstance(database_field, DatabaseField) and database_field.name != projection.alias:
                projection.hidden = False
        return lowered

    def _selects_expression_field(self, join: ast.JoinExpr | None, name: str) -> bool:
        while join is not None:
            table_type = join.type
            while isinstance(table_type, (ast.TableAliasType, ast.ColumnAliasedTableType)):
                table_type = table_type.table_type
            if isinstance(table_type, ast.TableType) and isinstance(table_type.table.fields.get(name), ExpressionField):
                return True
            join = join.next_join
        return False


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
                table=ast.Field(chain=[TRINO_UNNEST_TABLE_NAME]),
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
        if isinstance(node.args[0], ast.Call) and node.args[0].name.lower() == "aggregate_funnel_trends":
            return ast.Call(
                name="arrayElement",
                args=[self.visit(node.args[0]), ast.Constant(value=1)],
            )
        table_name = f"__trino_array_function_{self.unnest_index}"
        output_name = f"value_{self.unnest_index}"
        self.unnest_index += 1
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
        table_name = f"__trino_unnest_{self.unnest_index}"
        self.unnest_index += 1
        final_join = node.select_from
        while final_join.next_join is not None:
            final_join = final_join.next_join
        final_join.next_join = ast.JoinExpr(
            join_type="CROSS JOIN",
            table=ast.Field(chain=[TRINO_UNNEST_TABLE_NAME]),
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
        if all(
            isinstance(arg, ast.Constant) and not isinstance(arg.value, bool) and isinstance(arg.value, int)
            for arg in args
        ):
            values = [arg.value for arg in args if isinstance(arg, ast.Constant) and isinstance(arg.value, int)]
            constant_start, constant_count = (0, values[0]) if len(values) == 1 else values
            if constant_count < 0:
                raise TrinoLoweringError("TRINO_NUMBERS_NEGATIVE_ROW_COUNT", "numbers with a negative row count")
            if constant_count > _MAX_NUMBERS_ROWS:
                raise TrinoLoweringError(
                    "TRINO_NUMBERS_ROW_LIMIT_EXCEEDED", f"numbers above the {_MAX_NUMBERS_ROWS:,}-row limit"
                )
            return ast.Call(
                name="range",
                args=[ast.Constant(value=constant_start), ast.Constant(value=constant_start + constant_count)],
            )

        start_expr = ast.Constant(value=0) if len(args) == 1 else args[0]
        count_expr = args[-1]
        bounded_count = ast.Call(
            name="least",
            args=[
                ast.Call(name="greatest", args=[ast.Call(name="toInt", args=[count_expr]), ast.Constant(value=0)]),
                ast.Constant(value=_MAX_NUMBERS_ROWS),
            ],
        )
        return ast.Call(
            name="range",
            args=[
                start_expr,
                ast.ArithmeticOperation(op=ast.ArithmeticOperationOp.Add, left=start_expr, right=bounded_count),
            ],
        )


def normalize_trino_ast(node: ast.AST, context: HogQLContext) -> ast.AST:
    lowered = TrinoScalarCTELowerer().visit(node)
    lowered = TrinoArrayJoinFunctionLowerer(context).visit(lowered)
    lowered = TrinoPhysicalFieldLowerer(context).visit(lowered)
    lowered = TrinoSemanticCallLowerer().visit(lowered)
    lowered = lower_trino_any_joins(lowered)
    lowered = lower_trino_query_wrappers(lowered)
    lowered = TrinoSelectAliasLowerer().visit(lowered)
    lowered = TrinoPhysicalProjectionAliasLowerer(context).visit(lowered)
    TrinoNormalizer(context).visit(lowered)
    return lowered
