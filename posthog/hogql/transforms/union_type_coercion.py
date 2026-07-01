from __future__ import annotations

from posthog.hogql import ast
from posthog.hogql.base import _T_AST
from posthog.hogql.context import HogQLContext
from posthog.hogql.type_system import runtime_type_from_constant_type
from posthog.hogql.visitor import TraversingVisitor

# The resolver already computes the least common supertype of each UNION column, but ClickHouse never
# sees it: left to reconcile mismatched branch types itself, it lands on a Variant(...) type. sum() then
# rejects the Variant server-side, and clickhouse_driver can't deserialize it client-side (surfacing as a
# generic "A server error occurred."). We fix both by casting each branch column to the computed supertype
# so ClickHouse is handed one concrete type per column and never infers a Variant.
#
# Only cross-family unifications need a cast: same-family branches (Int32 + Int64, Float32 + Float64,
# differing Decimal precisions) already promote to a common type without a Variant. We coerce only to the
# families we can print a lossless cast for (see BasePrinter.visit_type_cast). Integer/boolean targets are
# deliberately excluded — they arise only from integer/boolean branches, which ClickHouse already promotes.
_CASTABLE_TARGET_FAMILY_TO_TYPE_NAME: dict[str, str] = {
    "float": "float",
    "datetime": "datetime",
    "string": "string",
}


def coerce_union_column_types(node: _T_AST, context: HogQLContext) -> _T_AST:
    """Cast UNION branch columns to the resolver's computed supertype so ClickHouse never infers a Variant."""
    _UnionTypeCoercer(context).visit(node)
    return node


class _UnionTypeCoercer(TraversingVisitor):
    def __init__(self, context: HogQLContext) -> None:
        self.context = context

    def visit_select_set_query(self, node: ast.SelectSetQuery) -> None:
        # Visit children first so nested unions are coerced to their own supertype before this level pushes
        # its (potentially wider) supertype further down.
        super().visit_select_set_query(node)
        if not isinstance(node.type, ast.SelectSetQueryType) or not node.type.columns:
            return
        targets = list(node.type.columns.items())
        self._coerce_query_columns(node.initial_select_query, targets)
        for sub in node.subsequent_select_queries:
            self._coerce_query_columns(sub.select_query, targets)

    def _coerce_query_columns(
        self, query: ast.SelectQuery | ast.SelectSetQuery, targets: list[tuple[str, ast.Type]]
    ) -> None:
        if isinstance(query, ast.SelectSetQuery):
            # A nested union projects columns through its own branches; push the outer supertype down to
            # its leaves so the whole subtree agrees on one type.
            self._coerce_query_columns(query.initial_select_query, targets)
            for sub in query.subsequent_select_queries:
                self._coerce_query_columns(sub.select_query, targets)
            return
        # Only touch plainly positional projections; anything unusual (asterisks, hidden helper aliases,
        # spreads) is left exactly as-is rather than risk misaligning columns with targets.
        if len(query.select) != len(targets):
            return
        for index, (name, target_type) in enumerate(targets):
            coerced = self._maybe_cast_column(query.select[index], name, target_type)
            if coerced is not None:
                query.select[index] = coerced

    def _maybe_cast_column(self, column: ast.Expr, name: str, target_type: ast.Type) -> ast.Expr | None:
        if not isinstance(target_type, ast.ConstantType):
            return None
        target_family = runtime_type_from_constant_type(target_type).family
        type_name = _CASTABLE_TARGET_FAMILY_TO_TYPE_NAME.get(target_family)
        if type_name is None:
            return None

        # A hidden alias isn't a real output column and shouldn't be counted positionally — bail out of the
        # whole branch to stay aligned.
        if isinstance(column, ast.Alias) and column.hidden:
            return None

        inner = column.expr if isinstance(column, ast.Alias) else column
        if inner.type is None:
            return None
        source_family = runtime_type_from_constant_type(inner.type.resolve_constant_type(self.context)).family
        if source_family == target_family:
            return None

        cast_expr = ast.TypeCast(expr=inner, type_name=type_name, type=target_type)
        if isinstance(column, ast.Alias):
            return ast.Alias(alias=column.alias, expr=cast_expr, type=column.type)
        # A bare column carries its output name implicitly; re-alias so the (first-branch) column name that
        # outer queries reference survives the wrap.
        return ast.Alias(alias=name, expr=cast_expr, type=ast.FieldAliasType(alias=name, type=target_type))
