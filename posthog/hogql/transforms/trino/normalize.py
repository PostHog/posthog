import bisect
import dataclasses
from typing import TypeVar

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.models import DatabaseField
from posthog.hogql.database.schema.numbers import NumbersTable
from posthog.hogql.database.trino_unnest_table import TRINO_UNNEST_TABLE_NAME
from posthog.hogql.errors import QueryError
from posthog.hogql.functions.mapping import find_hogql_aggregation
from posthog.hogql.resolver_utils import lookup_field_by_name
from posthog.hogql.transforms.trino.any_join import lower_trino_any_joins
from posthog.hogql.transforms.trino.asof_join import TrinoAsOfJoinLowerer
from posthog.hogql.transforms.trino.errors import TrinoLoweringError
from posthog.hogql.transforms.trino.expressions import expression_key, positional_index
from posthog.hogql.transforms.trino.limits import TrinoCompilationBudget
from posthog.hogql.transforms.trino.query_wrappers import _AggregateFunctionFinder, lower_trino_query_wrappers
from posthog.hogql.visitor import CloningVisitor, TraversingVisitor, clone_expr

from posthog.dataclasses import frozen

_T_AST = TypeVar("_T_AST", bound=ast.AST | None)

_MAX_NUMBERS_ROWS = 10_000
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


class TrinoUnpivotLowerer(CloningVisitor):
    def __init__(self, context: HogQLContext) -> None:
        super().__init__(clear_types=False)
        self.context = context
        self.index = 0

    def visit_unpivot_expr(self, node: ast.UnpivotExpr) -> ast.SelectQuery:
        lowered = super().visit_unpivot_expr(node)
        if len(lowered.columns) != 1 or not isinstance(lowered.type, ast.SelectQueryType):
            raise TrinoLoweringError(
                "TRINO_UNPIVOT_SHAPE_UNSUPPORTED", "UNPIVOT without a resolved single column group", node
            )
        column = lowered.columns[0]
        if not isinstance(column.value_columns, ast.Field) or not isinstance(column.name_columns, ast.Field):
            raise TrinoLoweringError("TRINO_UNPIVOT_SHAPE_UNSUPPORTED", "UNPIVOT tuple outputs", node)
        value_name = str(column.value_columns.chain[-1])
        label_name = str(column.name_columns.chain[-1])
        if value_name == label_name or not column.unpivot_values:
            raise TrinoLoweringError(
                "TRINO_UNPIVOT_SHAPE_UNSUPPORTED", "UNPIVOT without distinct output names or inputs", node
            )
        rows: list[ast.Expr] = []
        value_types: set[type[ast.ConstantType]] = set()
        for value in column.unpivot_values:
            if not isinstance(value, ast.Field):
                raise TrinoLoweringError("TRINO_UNPIVOT_SHAPE_UNSUPPORTED", "UNPIVOT input that is not a field", value)
            value_type = value.type.resolve_constant_type(self.context) if value.type else ast.UnknownType()
            if not isinstance(value_type, ast.UnknownType):
                value_types.add(type(value_type))
            binding = value.type
            while isinstance(binding, ast.FieldAliasType):
                binding = binding.type
            label = binding.name if isinstance(binding, ast.FieldType) else str(value.chain[-1])
            rows.append(ast.Call(name="tuple", args=[value, ast.Constant(value=label)]))
        if len(value_types) > 1 and not value_types <= {ast.IntegerType, ast.FloatType}:
            raise TrinoLoweringError("TRINO_UNPIVOT_TYPE_UNSUPPORTED", "UNPIVOT with incompatible value types", node)
        if isinstance(lowered.table, ast.JoinExpr):
            source = lowered.table
        elif isinstance(
            lowered.table,
            (ast.Field, ast.SelectQuery, ast.SelectSetQuery, ast.ValuesQuery, ast.UnpivotExpr, ast.PivotExpr),
        ):
            source = ast.JoinExpr(table=lowered.table)
        else:
            raise TrinoLoweringError("TRINO_UNPIVOT_SOURCE_UNSUPPORTED", "UNPIVOT without a table source", node)
        alias = f"__hogql_unpivot_{self.index}"
        self.index += 1
        aliases: set[str] = set()
        relation: ast.JoinExpr | None = source
        while relation is not None:
            if relation.alias is not None:
                aliases.add(relation.alias)
            elif isinstance(relation.table, ast.Field) and isinstance(relation.table.chain[-1], str):
                aliases.add(relation.table.chain[-1])
            relation = relation.next_join
        while alias in aliases:
            alias += "_"
        final_join = source
        while final_join.next_join is not None:
            final_join = final_join.next_join
        final_join.next_join = ast.JoinExpr(
            join_type="CROSS JOIN",
            table=ast.Field(chain=[TRINO_UNNEST_TABLE_NAME]),
            table_args=[ast.Array(exprs=rows)],
            alias=alias,
            column_aliases=[value_name, label_name],
        )
        return ast.SelectQuery(
            type=lowered.type,
            select=[
                ast.Field(chain=[alias, name]) if name in {value_name, label_name} else ast.Field(chain=[name])
                for name in lowered.type.columns
            ],
            select_from=source,
            where=(
                None
                if lowered.include_nulls
                else ast.Call(name="isNotNull", args=[ast.Field(chain=[alias, value_name])])
            ),
        )


class TrinoPhysicalFieldLowerer(CloningVisitor):
    def __init__(self, context: HogQLContext, *, physical_names: bool) -> None:
        super().__init__(clear_types=False)
        self.context = context
        self.physical_names = physical_names
        self.scopes: list[ast.SelectQueryType] = []

    def visit_select_query(self, node: ast.SelectQuery) -> ast.SelectQuery:
        if not isinstance(node.type, ast.SelectQueryType):
            return super().visit_select_query(node)
        self.scopes.append(node.type)
        try:
            return super().visit_select_query(node)
        finally:
            self.scopes.pop()

    def _source_alias(self, table_type: ast.TableOrSelectType) -> str | None:
        for scope in reversed(self.scopes):
            for alias, source_type in scope.tables.items():
                if source_type is table_type:
                    return alias
        return None

    def _backing_column_chain(
        self, node: ast.Field, source_type: ast.TableOrSelectType | None, column: str
    ) -> list[str | int]:
        qualifier = node.chain[:-1]
        if not qualifier and source_type is not None:
            source_alias = self._source_alias(source_type)
            qualifier = [source_alias] if source_alias is not None else []
        return [*qualifier, column]

    def visit_field(self, node: ast.Field) -> ast.Expr:
        field_type = node.type
        while isinstance(field_type, ast.FieldAliasType):
            field_type = field_type.type
        source_type = field_type.table_type if isinstance(field_type, ast.FieldType) else None
        table_type = source_type
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
                expr=ast.Field(
                    chain=self._backing_column_chain(node, source_type, "properties"),
                    type=ast.FieldType(name="properties", table_type=field_type.table_type),
                ),
                keys=[field_type.name],
                type=ast.StringType(nullable=True),
            )
        if isinstance(field_type, ast.FieldType) and is_events_field:
            source = ast.Field(chain=self._backing_column_chain(node, source_type, "elements_chain"))
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
        if isinstance(node.type, ast.FieldType) and isinstance(table_type, ast.TableType):
            database_field = node.type.resolve_database_field(self.context)
            if isinstance(database_field, DatabaseField) and database_field.name != node.type.name:
                lowered = super().visit_field(node)
                if self.physical_names:
                    lowered.chain[-1] = database_field.name
                if len(lowered.chain) == 1 and source_type is not None:
                    # The second resolver pass cannot recover the source of a renamed bare field.
                    source_alias = self._source_alias(source_type)
                    if source_alias is not None:
                        lowered.chain.insert(0, source_alias)
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
    def __init__(self, budget: TrinoCompilationBudget) -> None:
        super().__init__(clear_types=False)
        self.scalar_ctes: dict[str, ast.Expr] = {}
        self.expansion_budget = budget

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
        if (
            isinstance(node.type, ast.FieldAliasType)
            and len(node.chain) == 1
            and isinstance(node.chain[0], str)
            and node.chain[0] in self.scalar_ctes
        ):
            self.expansion_budget.visit(self.scalar_ctes[node.chain[0]])
            return clone_expr(self.scalar_ctes[node.chain[0]], clear_types=False)
        return super().visit_field(node)


class _InlineAliasCollector(TraversingVisitor):
    def __init__(self) -> None:
        super().__init__()
        self.aliases: dict[str, ast.Expr] = {}

    def visit(self, node: ast.AST | None) -> None:
        if isinstance(node, ast.Type):
            return
        super().visit(node)

    def visit_alias(self, node: ast.Alias) -> None:
        if not node.hidden:
            self.aliases.setdefault(node.alias, node.expr)
        super().visit_alias(node)

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        return None

    def visit_select_set_query(self, node: ast.SelectSetQuery) -> None:
        return None

    def visit_lambda(self, node: ast.Lambda) -> None:
        return None


class _InlineAliasHider(TraversingVisitor):
    def visit(self, node: ast.AST | None) -> None:
        if isinstance(node, ast.Type):
            return
        super().visit(node)

    def visit_alias(self, node: ast.Alias) -> None:
        node.hidden = True
        super().visit_alias(node)

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        return None

    def visit_select_set_query(self, node: ast.SelectSetQuery) -> None:
        return None

    def visit_lambda(self, node: ast.Lambda) -> None:
        return None


class _QualifiedFieldFinder(TraversingVisitor):
    def __init__(self) -> None:
        super().__init__()
        self.qualifiers: set[str] = set()

    def visit_field(self, node: ast.Field) -> None:
        if len(node.chain) > 1 and isinstance(node.chain[0], str):
            self.qualifiers.add(node.chain[0])

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        return None


class TrinoSelectAliasLowerer(CloningVisitor):
    def __init__(self, context: HogQLContext, budget: TrinoCompilationBudget) -> None:
        super().__init__(clear_types=False)
        self.context = context
        self.lambda_scopes: list[ast.SelectQueryType | None] = []
        self.aliases: dict[str, ast.Expr] = {}
        self.alias_positions: dict[str, int] = {}
        self.expanding: set[str] = set()
        self.in_order_by = False
        self.in_window = False
        self.expansion_budget = budget

    def visit(self, node: _T_AST) -> _T_AST:
        self.expansion_budget.consume_node(node)
        return super().visit(node)

    def visit_select_query(self, node: ast.SelectQuery) -> ast.SelectQuery:
        outer_aliases = self.aliases
        outer_alias_positions = self.alias_positions
        outer_in_order_by = self.in_order_by
        outer_in_window = self.in_window
        self.in_order_by = False
        self.in_window = False
        named_projections = self._named_projections(node.select)
        self.aliases = {name: expr.expr for name, (_, expr) in named_projections.items()}
        # Trino can't read a name given inside a projection, as in `(id AS y) + 1 AS x`, so those expand too.
        inline_aliases = _InlineAliasCollector()
        for expr in node.select:
            inline_aliases.visit(expr.expr if isinstance(expr, ast.Alias) else expr)
        for name, expr in inline_aliases.aliases.items():
            self.aliases.setdefault(name, expr)
        self.alias_positions = {name: position for name, (position, _) in named_projections.items()}
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
            alias_positions = self.alias_positions
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
        for order in lowered.order_by or []:
            order_expression = order.expr
            while isinstance(order_expression, ast.Alias) and order_expression.hidden:
                order_expression = order_expression.expr
            if (
                isinstance(order_expression, ast.Field)
                and len(order_expression.chain) > 1
                and isinstance(order_expression.chain[0], str)
                and order_expression.chain[0] in self.aliases
                and isinstance(order_expression.chain[-1], str)
                and order_expression.chain[-1] in self.alias_positions
            ):
                order.expr = ast.PositionalRef(index=self.alias_positions[order_expression.chain[-1]])
        self.aliases = outer_aliases
        self.alias_positions = outer_alias_positions
        self.in_order_by = outer_in_order_by
        self.in_window = outer_in_window
        return lowered

    @staticmethod
    def _named_projections(select: list[ast.Expr]) -> dict[str, tuple[int, ast.Alias]]:
        # The resolver names every plain column after itself with a hidden alias. A name the query gave explicitly
        # refers to that projection, as in ClickHouse, even when a later column has the same name.
        explicit = {expr.alias for expr in select if isinstance(expr, ast.Alias) and not expr.hidden}
        return {
            expr.alias: (index, expr)
            for index, expr in enumerate(select, start=1)
            if isinstance(expr, ast.Alias) and (not expr.hidden or expr.alias not in explicit)
        }

    def visit_order_expr(self, node: ast.OrderExpr) -> ast.OrderExpr:
        outer_in_order_by = self.in_order_by
        # Only a query's own ORDER BY sees output aliases; a window's OVER (ORDER BY ...) does not.
        self.in_order_by = not self.in_window
        try:
            return super().visit_order_expr(node)
        finally:
            self.in_order_by = outer_in_order_by

    def visit_window_expr(self, node: ast.WindowExpr) -> ast.WindowExpr:
        outer_in_order_by, outer_in_window = self.in_order_by, self.in_window
        self.in_order_by, self.in_window = False, True
        try:
            return super().visit_window_expr(node)
        finally:
            self.in_order_by, self.in_window = outer_in_order_by, outer_in_window

    def visit_alias(self, node: ast.Alias) -> ast.Alias:
        if node.hidden:
            self.expansion_budget.visit(node)
            cloned = clone_expr(node, clear_types=False)
            inner = cloned
            while isinstance(inner.expr, ast.Alias) and inner.expr.hidden:
                inner = inner.expr
            qualified = self._qualified_shadowed_column(inner.expr)
            if qualified is not None:
                inner.expr = qualified
            return cloned
        already_expanding = node.alias in self.expanding
        self.expanding.add(node.alias)
        try:
            return super().visit_alias(node)
        finally:
            if not already_expanding:
                self.expanding.remove(node.alias)

    def visit_lambda(self, node: ast.Lambda) -> ast.Lambda:
        self.lambda_scopes.append(node.type if isinstance(node.type, ast.SelectQueryType) else None)
        try:
            return super().visit_lambda(node)
        finally:
            self.lambda_scopes.pop()

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
            and not _is_lambda_argument(node)
        ):
            alias = node.chain[0]
            self.expanding.add(alias)
            try:
                expanded = self.visit(self.aliases[alias])
            finally:
                self.expanding.remove(alias)
            # ClickHouse allows a projection to name a part of itself, as in `(id AS y) + 1 AS x`. The copy must
            # not define `y` again in the same scope, while the projection it came from still does.
            _InlineAliasHider().visit(expanded)
            # Trino resolves ORDER BY names against output columns first, so a qualifier that is also a projection
            # alias would read that output column. The output column itself already holds this value.
            if self.in_order_by and self._has_qualifier_named_like_an_alias(expanded):
                return clone_expr(node, clear_types=False)
            return expanded
        qualified = self._qualified_shadowed_column(node)
        if qualified is not None:
            return qualified
        return super().visit_field(node)

    def _has_qualifier_named_like_an_alias(self, node: ast.Expr) -> bool:
        finder = _QualifiedFieldFinder()
        finder.visit(node)
        return any(qualifier in self.aliases for qualifier in finder.qualifiers)

    def _qualified_shadowed_column(self, node: ast.Expr) -> ast.Field | None:
        # After alias inlining, a later resolver pass would bind a bare column named like a projection alias to the
        # alias. Qualifying it keeps the column the first pass chose.
        if not (
            isinstance(node, ast.Field)
            and len(node.chain) == 1
            and isinstance(node.chain[0], str)
            and node.chain[0] in self.aliases
            and isinstance(node.type, ast.FieldType)
        ):
            return None
        table_type = node.type.table_type
        if isinstance(table_type, (ast.TableAliasType, ast.CTETableAliasType, ast.SelectQueryAliasType)):
            qualifier = table_type.alias
        elif isinstance(table_type, ast.CTETableType):
            qualifier = table_type.name
        else:
            return None
        if self.lambda_scopes and self._lambda_reads_qualifier_as_field(qualifier):
            raise TrinoLoweringError(
                "TRINO_LAMBDA_QUALIFIER_AMBIGUOUS",
                "a lambda reading a column shadowed by a projection alias",
                node,
                detail=(
                    f"Inside a lambda, the table alias `{qualifier}` also names a column or alias, "
                    "so the Trino query could read the wrong value. Rename the table alias."
                ),
            )
        return ast.Field(
            start=node.start,
            end=node.end,
            chain=[qualifier, node.chain[0]],
            type=node.type,
            from_asterisk=node.from_asterisk,
        )

    def _lambda_reads_qualifier_as_field(self, qualifier: str) -> bool:
        # Inside a lambda the resolver looks up the head of a chain as a field before it tries table aliases, so the
        # second pass would bind `qualifier.column` to a field named like the qualifier. Without a lambda scope to
        # check, assume a collision.
        scope = self.lambda_scopes[-1]
        if scope is None:
            return True
        try:
            return lookup_field_by_name(scope, qualifier, self.context) is not None
        except QueryError:
            return True


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
            if not isinstance(expression, ast.Field):
                projection.hidden = False
                continue
            field_type = projection.expr.type
            while isinstance(field_type, ast.FieldAliasType):
                field_type = field_type.type
            if not isinstance(field_type, ast.FieldType):
                continue
            database_field = field_type.resolve_database_field(self.context)
            if isinstance(database_field, DatabaseField) and database_field.name != projection.alias:
                projection.hidden = False
        return lowered


class TrinoDuplicateOutputNameLowerer(CloningVisitor):
    """Give a later projection of a name an internal alias in a nested query.

    ClickHouse names the first of two columns `id` and the second `b.id`, so an outer `id` reads the first one. Trino
    keeps both as `id` and reports an outer reference to either as ambiguous.
    """

    def __init__(self) -> None:
        super().__init__(clear_types=False)
        self.depth = 0

    def visit_select_query(self, node: ast.SelectQuery) -> ast.SelectQuery:
        self.depth += 1
        try:
            lowered = super().visit_select_query(node)
        finally:
            self.depth -= 1
        if self.depth == 0:
            return lowered
        taken = {projection.alias for projection in lowered.select if isinstance(projection, ast.Alias)}
        holders: dict[str, ast.Alias] = {}
        # The suffix only grows, so each taken name is probed once and a crafted query cannot make this quadratic.
        suffix = 0
        for index, projection in enumerate(lowered.select):
            if not isinstance(projection, ast.Alias):
                continue
            holder = holders.get(projection.alias)
            if holder is None:
                holders[projection.alias] = projection
                continue
            # An outer reference binds to an explicit alias, so it is the plain column that gives up the name.
            renamed = holder if holder.hidden and not projection.hidden else projection
            if renamed is holder:
                holders[projection.alias] = projection
            suffix = max(suffix, index)
            while (alias := f"__hogql_duplicate_{renamed.alias}_{suffix}") in taken:
                suffix += 1
            suffix += 1
            taken.add(alias)
            renamed.alias = alias
            renamed.hidden = False
        return lowered


@frozen
class _AggregatedUnnest:
    query: ast.SelectQuery
    pending_unnests: list[tuple[str, str, ast.Expr]]


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
        if any(_reads_an_aggregate(array_expr) for _, _, array_expr in pending):
            aggregated = self._aggregate_before_unnest(lowered, pending)
            lowered, pending = aggregated.query, aggregated.pending_unnests
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

    def _aggregate_before_unnest(
        self, query: ast.SelectQuery, pending: list[tuple[str, str, ast.Expr]]
    ) -> _AggregatedUnnest:
        output_names = _aggregated_unnest_output_names(query, pending)
        assert isinstance(query.type, ast.SelectQueryType)
        unnested_positions = _positions_reading_names(
            query.select, output_names, {output_name for _, output_name, _ in pending}
        )
        unnested_names = {output_name for _, output_name, _ in pending} | {
            output_names[position] for position in unnested_positions
        }
        if any(_unresolved_names(projection) & unnested_names for projection in query.select):
            raise TrinoLoweringError(
                "TRINO_ARRAY_JOIN_AGGREGATE_FORWARD_REFERENCE",
                "a projection that reads an arrayJoin over aggregates defined after it",
                query,
            )
        for clause in [query.where, query.prewhere, query.having, *(query.group_by or [])]:
            if clause is not None and _read_names(clause) & unnested_names:
                raise TrinoLoweringError(
                    "TRINO_ARRAY_JOIN_AGGREGATE_FILTER_UNSUPPORTED",
                    "a filter or GROUP BY that reads an arrayJoin over aggregates",
                    clause,
                )

        source_alias = f"__trino_array_function_source_{self.unnest_index}"
        self.unnest_index += 1
        inner_select = [
            _named_projection(projection, name)
            for position, (projection, name) in enumerate(zip(query.select, output_names, strict=True))
            if position not in unnested_positions
        ]
        inner_columns = {name: query.type.columns[name] for name in output_names if name not in unnested_names}
        unnest_pending: list[tuple[str, str, ast.Expr]] = []
        for table_name, output_name, array_expr in pending:
            array_name = f"{table_name}_array"
            inner_select.append(ast.Alias(alias=array_name, expr=array_expr))
            inner_columns[array_name] = array_expr.type or ast.UnknownType()
            unnest_pending.append((table_name, output_name, ast.Field(chain=[source_alias, array_name])))

        reader = _UnnestedQueryReader(
            source_alias=source_alias, inner_select=inner_select, unnested_names=unnested_names
        )
        outer = ast.SelectQuery(
            ctes=query.ctes,
            type=ast.SelectQueryType(columns=dict(query.type.columns)),
            select=[
                ast.Alias(alias=name, expr=reader.visit(_unwrap_alias(projection)))
                if position in unnested_positions
                else ast.Field(chain=[source_alias, name])
                for position, (projection, name) in enumerate(zip(query.select, output_names, strict=True))
            ],
            select_from=ast.JoinExpr(table=query, alias=source_alias),
            distinct=query.distinct,
            order_by=[reader.visit_order_expr(order) for order in query.order_by] if query.order_by else None,
            limit=query.limit,
            offset=query.offset,
            limit_with_ties=query.limit_with_ties,
            limit_percent=query.limit_percent,
            view_name=query.view_name,
        )
        sorted_unnested_positions = sorted(unnested_positions)
        query.group_by = [
            _inner_group_by(expr, unnested_positions, sorted_unnested_positions) for expr in query.group_by or []
        ] or None
        query.select = inner_select
        query.type = dataclasses.replace(query.type, columns=inner_columns)
        _clear_outer_clauses(query)
        return _AggregatedUnnest(query=outer, pending_unnests=unnest_pending)

    def visit_call(self, node: ast.Call) -> ast.Expr:
        if node.name.lower() != "arrayjoin":
            return super().visit_call(node)
        if len(node.args) != 1:
            raise TrinoLoweringError("TRINO_ARRAY_JOIN_ARGUMENT_COUNT", "arrayJoin with other than one argument", node)
        table_name = f"__trino_array_function_{self.unnest_index}"
        output_name = f"value_{self.unnest_index}"
        self.unnest_index += 1
        self.pending_unnests.append((table_name, output_name, self.visit(node.args[0])))
        return ast.Field(chain=[output_name], start=node.start, end=node.end)


def _reads_an_aggregate(node: ast.Expr) -> bool:
    finder = _AggregateFunctionFinder()
    finder.visit(node)
    return finder.found


def _aggregated_unnest_output_names(query: ast.SelectQuery, pending: list[tuple[str, str, ast.Expr]]) -> list[str]:
    if not all(_reads_an_aggregate(array_expr) for _, _, array_expr in pending):
        raise TrinoLoweringError(
            "TRINO_ARRAY_JOIN_MIXED_AGGREGATION", "arrayJoin over aggregates next to arrayJoin over rows", query
        )
    if query.limit_by is not None or query.qualify is not None or query.window_exprs:
        raise TrinoLoweringError(
            "TRINO_ARRAY_JOIN_AGGREGATE_SHAPE_UNSUPPORTED",
            "arrayJoin over aggregates with LIMIT BY, QUALIFY, or WINDOW",
            query,
        )
    if not isinstance(query.type, ast.SelectQueryType) or len(query.type.columns) != len(query.select):
        raise TrinoLoweringError(
            "TRINO_WRAPPER_OUTPUT_TYPE_UNRESOLVED", "arrayJoin over aggregates without resolved output names", query
        )
    return list(query.type.columns)


def _inner_group_by(expr: ast.Expr, unnested_positions: set[int], sorted_unnested_positions: list[int]) -> ast.Expr:
    position = positional_index(expr)
    if position is None:
        return expr
    if position - 1 in unnested_positions:
        raise TrinoLoweringError(
            "TRINO_ARRAY_JOIN_AGGREGATE_FILTER_UNSUPPORTED", "GROUP BY an arrayJoin over aggregates", expr
        )
    return ast.PositionalRef(index=position - bisect.bisect_left(sorted_unnested_positions, position - 1))


def _clear_outer_clauses(query: ast.SelectQuery) -> None:
    query.ctes = None
    query.distinct = None
    query.order_by = None
    query.limit = None
    query.offset = None
    query.limit_with_ties = None
    query.limit_percent = None
    query.view_name = None


def _unwrap_alias(node: ast.Expr) -> ast.Expr:
    while isinstance(node, ast.Alias):
        node = node.expr
    return node


def _named_projection(projection: ast.Expr, name: str) -> ast.Expr:
    if isinstance(projection, ast.Alias) and projection.alias == name and not projection.hidden:
        return projection
    return ast.Alias(alias=name, expr=projection)


class _NameReadFinder(TraversingVisitor):
    def __init__(self) -> None:
        super().__init__()
        self.names: set[str] = set()

    def visit_field(self, node: ast.Field) -> None:
        if (
            node.chain
            and isinstance(node.chain[0], str)
            and (node.type is None or isinstance(node.type, ast.FieldAliasType))
            and not _is_lambda_argument(node)
        ):
            self.names.add(node.chain[0])


def _is_lambda_argument(node: ast.Field) -> bool:
    field_type = node.type
    while isinstance(field_type, ast.FieldAliasType):
        field_type = field_type.type
    return isinstance(field_type, ast.LambdaArgumentType)


class _UnresolvedNameFinder(TraversingVisitor):
    def __init__(self) -> None:
        super().__init__()
        self.names: set[str] = set()

    def visit_field(self, node: ast.Field) -> None:
        if isinstance(node.type, ast.UnresolvedFieldType) and node.chain and isinstance(node.chain[0], str):
            self.names.add(node.chain[0])


def _unresolved_names(node: ast.Expr) -> set[str]:
    finder = _UnresolvedNameFinder()
    finder.visit(node)
    return finder.names


def _read_names(node: ast.Expr) -> set[str]:
    finder = _NameReadFinder()
    finder.visit(node)
    return finder.names


def _positions_reading_names(select: list[ast.Expr], output_names: list[str], names: set[str]) -> set[int]:
    readers: dict[str, list[int]] = {}
    for position, projection in enumerate(select):
        for name in _read_names(projection):
            readers.setdefault(name, []).append(position)
    positions: set[int] = set()
    pending = list(names)
    while pending:
        for position in readers.pop(pending.pop(), []):
            if position not in positions:
                positions.add(position)
                pending.append(output_names[position])
    return positions


class _UnnestedQueryReader(CloningVisitor):
    def __init__(self, *, source_alias: str, inner_select: list[ast.Expr], unnested_names: set[str]) -> None:
        super().__init__(clear_types=False)
        self.source_alias = source_alias
        self.unnested_names = unnested_names
        self.inner_names = {projection.alias for projection in inner_select if isinstance(projection, ast.Alias)}
        self.inner_keys = {
            expression_key(projection): projection.alias
            for projection in inner_select
            if isinstance(projection, ast.Alias) and isinstance(_unwrap_alias(projection), ast.Field)
        }

    def visit_order_expr(self, node: ast.OrderExpr) -> ast.OrderExpr:
        if positional_index(node.expr) is not None:
            return clone_expr(node, clear_types=False)
        return super().visit_order_expr(node)

    def visit_select_query(self, node: ast.SelectQuery) -> ast.SelectQuery:
        raise TrinoLoweringError(
            "TRINO_ARRAY_JOIN_AGGREGATE_SHAPE_UNSUPPORTED", "a subquery next to an arrayJoin over aggregates", node
        )

    def visit_call(self, node: ast.Call) -> ast.Expr:
        if find_hogql_aggregation(node.name):
            raise TrinoLoweringError(
                "TRINO_ARRAY_JOIN_AGGREGATE_SHAPE_UNSUPPORTED",
                "an aggregate outside an arrayJoin over aggregates",
                node,
            )
        return super().visit_call(node)

    def visit_window_function(self, node: ast.WindowFunction) -> ast.Expr:
        raise TrinoLoweringError(
            "TRINO_ARRAY_JOIN_AGGREGATE_SHAPE_UNSUPPORTED",
            "a window function that reads an arrayJoin over aggregates",
            node,
        )

    def visit_field(self, node: ast.Field) -> ast.Field:
        head = node.chain[0] if node.chain else None
        if (
            node.type is None
            or _is_lambda_argument(node)
            or (isinstance(node.type, ast.FieldAliasType) and head in self.unnested_names)
        ):
            return clone_expr(node, clear_types=False)
        if isinstance(node.type, ast.FieldAliasType) and head in self.inner_names:
            return ast.Field(chain=[self.source_alias, *node.chain], start=node.start, end=node.end)
        name = self.inner_keys.get(expression_key(node))
        if name is None:
            raise TrinoLoweringError(
                "TRINO_ARRAY_JOIN_AGGREGATE_REFERENCE_NOT_PROJECTED",
                "a column next to an arrayJoin over aggregates that the aggregated query does not select",
                node,
            )
        return ast.Field(chain=[self.source_alias, name], start=node.start, end=node.end)


_NUMERIC_TYPES = (ast.IntegerType, ast.FloatType, ast.DecimalType)
_NEGATED_SUBQUERY_MEMBERSHIP = {
    ast.CompareOperationOp.In: False,
    ast.CompareOperationOp.GlobalIn: False,
    ast.CompareOperationOp.NotIn: True,
    ast.CompareOperationOp.GlobalNotIn: True,
}


@frozen
class _LambdaSet:
    alias: str

    @property
    def items_column(self) -> str:
        return f"{self.alias}_items"

    @property
    def has_null_column(self) -> str:
        return f"{self.alias}_has_null"


class TrinoLambdaSubqueryLowerer(CloningVisitor):
    def __init__(self, context: HogQLContext) -> None:
        super().__init__(clear_types=False)
        self.context = context
        self.lambda_args: list[list[str]] = []
        self.pending_sets: list[ast.JoinExpr] = []
        self.set_index = 0

    def visit_select_query(self, node: ast.SelectQuery) -> ast.SelectQuery:
        outer_lambda_args, outer_pending_sets = self.lambda_args, self.pending_sets
        self.lambda_args, self.pending_sets = [], []
        try:
            lowered = super().visit_select_query(node)
            pending_sets = self.pending_sets
        finally:
            self.lambda_args, self.pending_sets = outer_lambda_args, outer_pending_sets
        for join in pending_sets:
            _append_cross_join(lowered, join)
            _group_by_set_read_after_aggregation(lowered, join)
        return lowered

    def visit_lambda(self, node: ast.Lambda) -> ast.Lambda:
        self.lambda_args.append(node.args)
        try:
            return super().visit_lambda(node)
        finally:
            self.lambda_args.pop()

    def visit_compare_operation(self, node: ast.CompareOperation) -> ast.Expr:
        negated = _NEGATED_SUBQUERY_MEMBERSHIP.get(node.op)
        if not self.lambda_args or negated is None or not isinstance(node.right, (ast.SelectQuery, ast.SelectSetQuery)):
            return super().visit_compare_operation(node)
        if len(self.lambda_args) > 1:
            raise TrinoLoweringError(
                "TRINO_LAMBDA_SUBQUERY_NESTED", "a subquery inside a lambda nested in another lambda", node
            )
        if _read_lambda_arguments(node.right) & set(self.lambda_args[0]):
            raise TrinoLoweringError(
                "TRINO_LAMBDA_SUBQUERY_CORRELATED", "a subquery inside a lambda that reads a lambda argument", node
            )
        lambda_set = _LambdaSet(alias=f"__trino_lambda_set_{self.set_index}")
        self.set_index += 1
        value = _membership_value(self.visit(node.left), node.right, self.context)
        self.pending_sets.append(ast.JoinExpr(table=self._set_query(node.right, lambda_set), alias=lambda_set.alias))
        membership = ast.Call(
            name="coalesce",
            args=[
                ast.Call(name="has", args=[ast.Field(chain=[lambda_set.alias, lambda_set.items_column]), value]),
                ast.Field(chain=[lambda_set.alias, lambda_set.has_null_column]),
            ],
        )
        return ast.Not(expr=membership) if negated else membership

    def _set_query(self, subquery: ast.SelectQuery | ast.SelectSetQuery, lambda_set: _LambdaSet) -> ast.SelectQuery:
        lowered = self.visit(subquery)
        source_alias = f"{lambda_set.alias}_source"
        column = ast.Field(chain=[source_alias, _name_single_column(lowered, lambda_set.alias)])
        values = ast.Call(name="groupUniqArrayIf", args=[column, ast.Call(name="isNotNull", args=[clone_expr(column)])])
        has_null = ast.CompareOperation(
            op=ast.CompareOperationOp.Gt,
            left=ast.Call(name="countIf", args=[ast.Call(name="isNull", args=[clone_expr(column)])]),
            right=ast.Constant(value=0),
        )
        return ast.SelectQuery(
            select=[
                ast.Alias(
                    alias=lambda_set.items_column, expr=ast.Call(name="coalesce", args=[values, ast.Array(exprs=[])])
                ),
                ast.Alias(alias=lambda_set.has_null_column, expr=has_null),
            ],
            select_from=ast.JoinExpr(table=lowered, alias=source_alias),
        )


def _first_select_query(subquery: ast.SelectQuery | ast.SelectSetQuery) -> ast.SelectQuery:
    first = subquery
    while isinstance(first, ast.SelectSetQuery):
        first = first.initial_select_query
    if len(first.select) != 1:
        raise TrinoLoweringError(
            "TRINO_LAMBDA_SUBQUERY_SHAPE_UNSUPPORTED", "a subquery inside a lambda with more than one column", subquery
        )
    return first


def _name_single_column(subquery: ast.SelectQuery | ast.SelectSetQuery, alias: str) -> str:
    first = _first_select_query(subquery)
    projection = first.select[0]
    if isinstance(projection, ast.Alias):
        return projection.alias
    name = f"{alias}_value"
    first.select = [ast.Alias(alias=name, expr=projection)]
    if isinstance(first.type, ast.SelectQueryType):
        first.type = dataclasses.replace(first.type, columns={name: projection.type or ast.UnknownType()})
    return name


def _membership_value(
    value: ast.Expr, subquery: ast.SelectQuery | ast.SelectSetQuery, context: HogQLContext
) -> ast.Expr:
    value_type = _constant_type(value, context)
    set_type = _constant_type(_first_select_query(subquery).select[0], context)
    if isinstance(value_type, ast.StringType) and isinstance(set_type, _NUMERIC_TYPES):
        return ast.Call(name="toInt" if isinstance(set_type, ast.IntegerType) else "toFloat", args=[value])
    if isinstance(value_type, _NUMERIC_TYPES) and isinstance(set_type, ast.StringType):
        return ast.Call(name="toString", args=[value])
    return value


def _constant_type(node: ast.Expr, context: HogQLContext) -> ast.ConstantType | None:
    return node.type.resolve_constant_type(context) if node.type is not None else None


def _group_by_set_read_after_aggregation(query: ast.SelectQuery, join: ast.JoinExpr) -> None:
    assert join.alias is not None
    finder = _ReadOutsideAggregatesFinder(join.alias)
    for clause in [*query.select, query.having, *(order.expr for order in query.order_by or [])]:
        finder.visit(clause)
    if not finder.found or not _aggregates(query):
        return
    if not query.group_by or query.group_by_mode is not None:
        raise TrinoLoweringError(
            "TRINO_LAMBDA_SUBQUERY_IN_GLOBAL_AGGREGATE",
            "a subquery inside a lambda that runs after an aggregation without a plain GROUP BY",
            query,
        )
    lambda_set = _LambdaSet(alias=join.alias)
    query.group_by.extend(
        ast.Field(chain=[join.alias, column]) for column in [lambda_set.items_column, lambda_set.has_null_column]
    )


def _aggregates(query: ast.SelectQuery) -> bool:
    if query.group_by:
        return True
    finder = _AggregateFunctionFinder()
    for clause in [*query.select, query.having, *(order.expr for order in query.order_by or [])]:
        finder.visit(clause)
    return finder.found


class _ReadOutsideAggregatesFinder(TraversingVisitor):
    def __init__(self, alias: str) -> None:
        super().__init__()
        self.alias = alias
        self.found = False

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        return

    def visit_call(self, node: ast.Call) -> None:
        if not find_hogql_aggregation(node.name):
            super().visit_call(node)

    def visit_field(self, node: ast.Field) -> None:
        if node.chain and node.chain[0] == self.alias:
            self.found = True


class _LambdaArgumentFinder(TraversingVisitor):
    def __init__(self) -> None:
        super().__init__()
        self.names: set[str] = set()
        self.bound: list[list[str]] = []

    def visit_lambda(self, node: ast.Lambda) -> None:
        self.bound.append(node.args)
        try:
            super().visit_lambda(node)
        finally:
            self.bound.pop()

    def visit_field(self, node: ast.Field) -> None:
        field_type = node.type
        while isinstance(field_type, ast.FieldAliasType):
            field_type = field_type.type
        name = node.chain[0]
        if (
            isinstance(field_type, (ast.LambdaArgumentType, ast.UnresolvedFieldType))
            and isinstance(name, str)
            and not any(name in args for args in self.bound)
        ):
            self.names.add(name)


def _read_lambda_arguments(node: ast.Expr) -> set[str]:
    finder = _LambdaArgumentFinder()
    finder.visit(node)
    return finder.names


def _append_cross_join(query: ast.SelectQuery, join: ast.JoinExpr) -> None:
    if query.select_from is None:
        query.select_from = join
        return
    final_join = query.select_from
    while final_join.next_join is not None:
        final_join = final_join.next_join
    join.join_type = "CROSS JOIN"
    final_join.next_join = join


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
        self._lower_row_filter_having(node)
        super().visit_select_query(node)

    def _lower_row_filter_having(self, node: ast.SelectQuery) -> None:
        # ClickHouse reads HAVING without GROUP BY or aggregates as a row filter; Trino makes it a global aggregation.
        if node.having is None or node.group_by:
            return
        finder = _AggregateFunctionFinder()
        for expr in [*node.select, node.having, *(order.expr for order in node.order_by or [])]:
            finder.visit(expr)
        if finder.found:
            return
        node.where = ast.And(exprs=[node.where, node.having]) if node.where is not None else node.having
        node.having = None

    def _lower_array_join(self, node: ast.SelectQuery) -> None:
        if node.array_join_op is None and not node.array_join_list:
            return
        if node.array_join_op not in {"ARRAY JOIN", "INNER ARRAY JOIN", "LEFT ARRAY JOIN"}:
            raise TrinoLoweringError(
                "TRINO_ARRAY_JOIN_MODE_UNSUPPORTED", node.array_join_op or "ARRAY JOIN without an operation", node
            )
        if not node.array_join_list or not all(
            isinstance(array_expr, ast.Alias) for array_expr in node.array_join_list
        ):
            raise TrinoLoweringError("TRINO_ARRAY_JOIN_ALIAS_REQUIRED", "ARRAY JOIN without an output alias", node)
        array_exprs = [array_expr for array_expr in node.array_join_list if isinstance(array_expr, ast.Alias)]
        table_name = f"__trino_unnest_{self.unnest_index}"
        self.unnest_index += 1
        elements: ast.Expr = (
            _wrap_unnest_elements(array_exprs[0].expr, f"{table_name}_value")
            if len(array_exprs) == 1
            else ast.Call(name="arrayZip", args=[array_expr.expr for array_expr in array_exprs])
        )
        if node.array_join_op == "LEFT ARRAY JOIN":
            defaults = []
            for array_expr in array_exprs:
                array_type = array_expr.expr.type.resolve_constant_type(self.context) if array_expr.expr.type else None
                if not isinstance(array_type, ast.ArrayType):
                    raise TrinoLoweringError(
                        "TRINO_ARRAY_JOIN_DEFAULT_TYPE_REQUIRED",
                        "LEFT ARRAY JOIN without an array item type",
                        array_expr,
                    )
                defaults.append(self._array_default(array_type.item_type))
            elements = ast.Call(
                name="if",
                args=[
                    ast.Call(name="empty", args=[elements]),
                    ast.Array(exprs=[ast.Call(name="tuple", args=defaults)]),
                    elements,
                ],
            )
        unnest = ast.JoinExpr(
            table=ast.Field(chain=[TRINO_UNNEST_TABLE_NAME]),
            table_args=[elements],
            alias=table_name,
            column_aliases=[array_expr.alias for array_expr in array_exprs],
        )
        final_join = node.select_from
        if final_join is None:
            node.select_from = unnest
        else:
            while final_join.next_join is not None:
                final_join = final_join.next_join
            unnest.join_type = "CROSS JOIN"
            final_join.next_join = unnest
        node.array_join_op = None
        node.array_join_list = None

    def _array_default(self, item_type: ast.ConstantType) -> ast.Expr:
        if isinstance(item_type, ast.UnknownType) and item_type.unanalyzable:
            raise TrinoLoweringError(
                "TRINO_ARRAY_JOIN_DEFAULT_TYPE_REQUIRED", "LEFT ARRAY JOIN with an unknown item type"
            )
        if item_type.nullable:
            return ast.Constant(value=None)
        if isinstance(item_type, ast.StringType):
            return ast.Constant(value="")
        if isinstance(item_type, ast.IntegerType):
            return ast.Constant(value=0)
        if isinstance(item_type, ast.FloatType):
            return ast.Constant(value=0.0)
        if isinstance(item_type, ast.BooleanType):
            return ast.Constant(value=False)
        if isinstance(item_type, ast.ArrayType):
            return ast.Array(exprs=[])
        if isinstance(item_type, ast.TupleType):
            return ast.Call(name="tuple", args=[self._array_default(nested) for nested in item_type.item_types])
        raise TrinoLoweringError("TRINO_ARRAY_JOIN_DEFAULT_TYPE_UNSUPPORTED", item_type.print_type())

    def visit_join_expr(self, node: ast.JoinExpr) -> None:
        if node.join_type is not None and node.join_type.startswith("GLOBAL "):
            node.join_type = node.join_type.removeprefix("GLOBAL ")
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


def normalize_trino_ast(node: ast.AST, context: HogQLContext, *, physical_names: bool = True) -> ast.AST:
    budget = TrinoCompilationBudget()
    budget.visit(node)
    lowered = TrinoScalarCTELowerer(budget).visit(node)
    lowered = TrinoUnpivotLowerer(context).visit(lowered)
    lowered = TrinoLambdaSubqueryLowerer(context).visit(lowered)
    lowered = TrinoArrayJoinFunctionLowerer(context).visit(lowered)
    lowered = TrinoPhysicalFieldLowerer(context, physical_names=physical_names).visit(lowered)
    lowered = TrinoSemanticCallLowerer().visit(lowered)
    lowered = TrinoAsOfJoinLowerer().visit(lowered)
    lowered = lower_trino_any_joins(lowered, physical_names=physical_names)
    lowered = lower_trino_query_wrappers(lowered)
    lowered = TrinoSelectAliasLowerer(context, budget).visit(lowered)
    lowered = TrinoPhysicalProjectionAliasLowerer(context).visit(lowered)
    lowered = TrinoDuplicateOutputNameLowerer().visit(lowered)
    TrinoNormalizer(context).visit(lowered)
    return lowered
