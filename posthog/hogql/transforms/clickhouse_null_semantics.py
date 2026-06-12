"""ClickHouse pass: lower HogQL's comparison null semantics to explicit AST.

In HogQL a comparison is two-valued: `a = b` is true or false, even when a side is NULL. ClickHouse comparisons are
three-valued — `equals(a, b)` is NULL when either side is NULL — so a comparison over nullable operands must be wrapped
(`ifNull(equals(a, b), 0)`) to keep the HogQL meaning. The printer used to decide this wrapping while rendering SQL
strings, which meant no pass could ever see or simplify the wraps, and the index-protecting exemptions had to match
printed SQL text. This pass makes the same decisions as AST rewrites instead: after it runs, every comparison is either
provably two-valued (printed bare) or explicitly wrapped, and the printer prints what it is given.

The rules are semantics-preserving, not stylistic:

- `ifNull(cmp, 0 or 1)` restores the comparison's value when a nullable side is NULL (false for `=` / `LIKE`, true for
  `!=` / `NOT LIKE`).
- `x = NULL` / `x != NULL` become `isNull(x)` / `isNotNull(x)`.
- Comparisons between two constants fold to a 0/1 constant.
- Inside a JOIN constraint or an `indexHint(...)` call nothing is wrapped: join keys must stay bare for hash joins, and
  indexHint is an optimizer directive whose result does not matter.

A few operands are exempted from wrapping even when their resolved type says "nullable", because an `ifNull(...)` around
them would hide a primary-key or skip-index column from the planner (see `_comparison_is_index_protected`). These
reproduce the printer's old exemptions, which matched printed SQL substrings, as checks on the actual AST.

ClickHouse only, and it must run after every pass that creates or rewrites comparisons (property resolution, predicate
pushdown, cohort joins), so the wrapping decision sees the final operand shapes and their types. A pass that emits a
deliberately bare comparison marks it by typing the operands non-nullable — see e.g. the bare-column rewrites in
`clickhouse_property_resolution.py`.
"""

from typing import cast

from posthog.hogql import ast
from posthog.hogql.base import _T_AST
from posthog.hogql.context import HogQLContext
from posthog.hogql.errors import ImpossibleASTError, InternalHogQLError
from posthog.hogql.functions.mapping import HOGQL_COMPARISON_MAPPING
from posthog.hogql.printer.base import resolve_field_type
from posthog.hogql.transforms.clickhouse_property_resolution import AI_BLOOM_FILTER_COLUMNS
from posthog.hogql.visitor import CloningVisitor, GetFieldsTraverser, clone_expr

# Tables whose timestamp(-suffixed) columns anchor the primary key: an ifNull() around them would defeat index pruning,
# so comparisons touching them are never wrapped. The columns are non-nullable in ClickHouse; this exemption papers over
# resolved types that don't say so (e.g. a timestamp projected through a subquery or wrapped in toTimeZone).
PROTECTED_TIMESTAMP_TABLES = (
    "events",
    "raw_sessions",
    "raw_sessions_v3",
    "session_replay_events",
    "raw_session_replay_events",
)


def _bool_type() -> ast.BooleanType:
    # A fresh instance per node — type objects are mutable models, so sharing one across the tree invites aliasing bugs.
    return ast.BooleanType(nullable=False)


def _is_type_nullable(node_type: ast.Type, context: HogQLContext) -> bool | None:
    if isinstance(node_type, ast.PropertyType):
        return True
    elif isinstance(node_type, ast.ConstantType):
        return node_type.nullable
    elif isinstance(node_type, ast.CallType):
        return node_type.return_type.nullable
    elif isinstance(node_type, ast.FieldType):
        # A field reading from a subquery (alias) has no database field, so `is_nullable` defaults to True and
        # over-wraps the column in `ifNull(...)`. Its real nullability is the projected column's constant type —
        # use that, so a non-nullable value selected from a subquery isn't needlessly null-wrapped (which, for a
        # join key, ClickHouse can't use). Real-table fields keep `is_nullable` (identical result, no risk).
        if not isinstance(node_type.table_type, ast.BaseTableType):
            try:
                return node_type.resolve_constant_type(context).nullable
            except Exception:
                return True
        return node_type.is_nullable(context)
    return None


def is_nullable(node: ast.Expr, context: HogQLContext) -> bool:
    if isinstance(node, ast.Constant):
        return node.value is None
    elif node.type and (nullable := _is_type_nullable(node.type, context)) is not None:
        return nullable
    elif isinstance(node, ast.Alias):
        return is_nullable(node.expr, context)
    elif (
        isinstance(node.type, ast.FieldAliasType)
        and (field_type := resolve_field_type(node))
        and (nullable := _is_type_nullable(field_type, context)) is not None
    ):
        return nullable
    return True


def _references_protected_timestamp(expr: ast.Expr) -> bool:
    """True when the operand reads a timestamp(-suffixed) column of a `PROTECTED_TIMESTAMP_TABLES` table."""
    for field in GetFieldsTraverser(expr).fields:
        if not isinstance(field.type, ast.FieldType):
            continue
        field_name = str(field.chain[-1]) if field.chain else ""
        if not (field_name == "timestamp" or field_name.endswith("_timestamp")):
            continue

        table_type: ast.Type | None = field.type.table_type
        while table_type is not None:
            if isinstance(table_type, ast.TableType):
                if table_type.table.to_printed_hogql() in PROTECTED_TIMESTAMP_TABLES:
                    return True
                break
            if isinstance(
                table_type, (ast.LazyJoinType, ast.VirtualTableType, ast.TableAliasType, ast.ColumnAliasedTableType)
            ):
                table_type = table_type.table_type
            else:
                break
    return False


def _is_session_v2_timestamp_expr(expr: ast.Expr) -> bool:
    """True when the operand is the sessions-v2 session-start derivation:
    `fromUnixTimestamp(intDiv(toUInt64(bitShiftRight(session_id_v7, 80)), 1000))`.

    `session_id_v7` is a non-nullable UInt128, so the whole expression is non-nullable — and it is the table's primary
    key derivation, so an `ifNull(...)` around a comparison against it would defeat index pruning.
    """
    while isinstance(expr, ast.Alias) and expr.hidden:
        expr = expr.expr
    if not (isinstance(expr, ast.Call) and expr.name == "fromUnixTimestamp" and len(expr.args) == 1):
        return False
    int_div = expr.args[0]
    if not (isinstance(int_div, ast.Call) and int_div.name == "intDiv" and len(int_div.args) == 2):
        return False
    if not (isinstance(int_div.args[1], ast.Constant) and int_div.args[1].value == 1000):
        return False
    to_uint = int_div.args[0]
    if not (isinstance(to_uint, ast.Call) and to_uint.name in ("toUInt64", "_toUInt64") and len(to_uint.args) == 1):
        return False
    shift = to_uint.args[0]
    if not (isinstance(shift, ast.Call) and shift.name == "bitShiftRight" and len(shift.args) == 2):
        return False
    if not (isinstance(shift.args[1], ast.Constant) and shift.args[1].value == 80):
        return False
    field = shift.args[0]
    return isinstance(field, ast.Field) and bool(field.chain) and str(field.chain[-1]) == "session_id_v7"


def _references_ai_bloom_column(expr: ast.Expr) -> bool:
    """True when the operand reads one of the $ai_* materialized columns, whose bloom-filter indexes only work bare."""
    for field in GetFieldsTraverser(expr).fields:
        names = {str(field.chain[-1])} if field.chain else set()
        if isinstance(field.type, (ast.FieldType, ast.FieldAliasType)):
            names.add(field.type.name if isinstance(field.type, ast.FieldType) else field.type.alias)
        if names & AI_BLOOM_FILTER_COLUMNS:
            return True
    return False


def _comparison_is_index_protected(left: ast.Expr, right: ast.Expr) -> bool:
    return (
        _references_protected_timestamp(left)
        or _references_protected_timestamp(right)
        or _is_session_v2_timestamp_expr(left)
        or _is_session_v2_timestamp_expr(right)
        or _references_ai_bloom_column(left)
        or _references_ai_bloom_column(right)
    )


def _bool_constant(value: bool) -> ast.Constant:
    return ast.Constant(value=1 if value else 0, type=_bool_type())


def _is_null(expr: ast.Expr) -> ast.Call:
    return ast.Call(name="isNull", args=[clone_expr(expr)], type=_bool_type())


def _is_not_null(expr: ast.Expr) -> ast.Call:
    return ast.Call(name="isNotNull", args=[clone_expr(expr)], type=_bool_type())


def _if_null(comparison: ast.Expr, fallback: ast.Expr) -> ast.Call:
    # Typed non-nullable bool — the resolver's type for the comparison itself — so a comparison nested inside another
    # comparison's operand contributes the same nullability it did before lowering.
    return ast.Call(name="ifNull", args=[comparison, fallback], type=_bool_type())


class NullSemanticsLowering(CloningVisitor):
    """Rewrites comparisons into their explicit ClickHouse null-safe form. See the module docstring."""

    def __init__(self, context: HogQLContext) -> None:
        # The lowered AST is printed directly after this pass, so keep resolved types rather than clearing them.
        super().__init__(clear_types=False)
        self.context = context
        self._join_constraint_depth = 0
        self._index_hint_depth = 0

    def visit_join_constraint(self, node: ast.JoinConstraint) -> ast.JoinConstraint:
        self._join_constraint_depth += 1
        try:
            return super().visit_join_constraint(node)
        finally:
            self._join_constraint_depth -= 1

    def visit_call(self, node: ast.Call) -> ast.Expr:
        if node.name == "indexHint":
            self._index_hint_depth += 1
            try:
                return super().visit_call(node)
            finally:
                self._index_hint_depth -= 1

        # A comparison written in call form (`equals(a, b)`) is still a comparison and needs the same null handling.
        # Mirrors the call-to-comparison routing the printer does, so both forms print identically.
        if node.name in HOGQL_COMPARISON_MAPPING and len(node.args) == 2:
            return self.visit_compare_operation(
                ast.CompareOperation(
                    left=node.args[0],
                    right=node.args[1],
                    op=HOGQL_COMPARISON_MAPPING[node.name],
                    type=node.type if isinstance(node.type, ast.ConstantType) else _bool_type(),
                )
            )

        return super().visit_call(node)

    def visit_compare_operation(self, node: ast.CompareOperation) -> ast.Expr:
        node = cast(ast.CompareOperation, super().visit_compare_operation(node))
        return self._lower_compare(node)

    def visit_between_expr(self, node: ast.BetweenExpr) -> ast.Expr:
        node = cast(ast.BetweenExpr, super().visit_between_expr(node))
        if (
            is_nullable(node.expr, self.context)
            or is_nullable(node.low, self.context)
            or is_nullable(node.high, self.context)
        ):
            return _if_null(node, _bool_constant(False))
        return node

    # And/Or constant folding stays in the printer: conjunctions are still built during printing (the team_id guard is
    # merged into WHERE/ON at print time), so a pass-level fold could never see them. The printer folds the 0/1
    # constants this pass produces along with everything else.

    def _lower_compare(self, node: ast.CompareOperation) -> ast.Expr:
        in_join_constraint = self._join_constraint_depth > 0
        # indexHint() is purely an optimizer directive — its result is always true,
        # so ifNull wrapping inside it is unnecessary and prevents index usage.
        in_index_hint = self._index_hint_depth > 0
        left, right = node.left, node.right
        nullable_left = is_nullable(left, self.context)
        nullable_right = is_nullable(right, self.context)
        not_nullable = (not nullable_left and not nullable_right) or _comparison_is_index_protected(left, right)

        constant_lambda = None
        value_if_one_side_is_null = False
        value_if_both_sides_are_null = False

        if node.op == ast.CompareOperationOp.Eq:
            constant_lambda = lambda left_op, right_op: left_op == right_op
            value_if_both_sides_are_null = True
        elif node.op == ast.CompareOperationOp.NotEq:
            constant_lambda = lambda left_op, right_op: left_op != right_op
            value_if_one_side_is_null = True
        elif node.op == ast.CompareOperationOp.Like:
            value_if_both_sides_are_null = True
        elif node.op == ast.CompareOperationOp.NotLike:
            value_if_one_side_is_null = True
        elif node.op == ast.CompareOperationOp.ILike:
            value_if_both_sides_are_null = True
        elif node.op == ast.CompareOperationOp.NotILike:
            value_if_one_side_is_null = True
        elif node.op == ast.CompareOperationOp.In:
            return node
        elif node.op == ast.CompareOperationOp.NotIn:
            # With transform_null_in=1, ClickHouse rewrites notIn() to notNullIn().
            # In Distributed aggregate plans this can make the coordinator expect
            # a pre-rewrite aggregate column name while shards return the rewritten
            # one, e.g. minIf(..., notIn(...)) vs minIf(..., notNullIn(...)).
            # Wrapping nullable NOT IN matches the existing nullable materialized
            # column path and preserves transform_null_in=1 semantics.
            if nullable_left and not not_nullable and not in_join_constraint and not in_index_hint:
                return _if_null(node, _bool_constant(True))
            return node
        elif node.op == ast.CompareOperationOp.GlobalIn:
            pass
        elif node.op == ast.CompareOperationOp.GlobalNotIn:
            pass
        elif node.op == ast.CompareOperationOp.Regex:
            value_if_both_sides_are_null = True
        elif node.op == ast.CompareOperationOp.NotRegex:
            value_if_one_side_is_null = True
        elif node.op == ast.CompareOperationOp.IRegex:
            value_if_both_sides_are_null = True
        elif node.op == ast.CompareOperationOp.NotIRegex:
            value_if_one_side_is_null = True
        elif node.op == ast.CompareOperationOp.Gt:
            constant_lambda = lambda left_op, right_op: (
                left_op > right_op if left_op is not None and right_op is not None else False
            )
        elif node.op == ast.CompareOperationOp.GtEq:
            constant_lambda = lambda left_op, right_op: (
                left_op >= right_op if left_op is not None and right_op is not None else False
            )
        elif node.op == ast.CompareOperationOp.Lt:
            constant_lambda = lambda left_op, right_op: (
                left_op < right_op if left_op is not None and right_op is not None else False
            )
        elif node.op == ast.CompareOperationOp.LtEq:
            constant_lambda = lambda left_op, right_op: (
                left_op <= right_op if left_op is not None and right_op is not None else False
            )
        elif node.op == ast.CompareOperationOp.InCohort or node.op == ast.CompareOperationOp.NotInCohort:
            raise InternalHogQLError("Cohort operations should have been resolved before printing")
        else:
            raise ImpossibleASTError(f"Unknown CompareOperationOp: {node.op.name}")

        # Can we compare constants?
        if isinstance(left, ast.Constant) and isinstance(right, ast.Constant) and constant_lambda is not None:
            return _bool_constant(constant_lambda(left.value, right.value))

        # Special cases when we should not add any null checks
        if in_join_constraint or not_nullable or in_index_hint:
            return node

        # Special optimization for "Eq" operator
        if node.op in (ast.CompareOperationOp.Eq, ast.CompareOperationOp.Like, ast.CompareOperationOp.ILike):
            if isinstance(right, ast.Constant):
                if right.value is None:
                    return _is_null(left)
                return _if_null(node, _bool_constant(False))
            elif isinstance(left, ast.Constant):
                if left.value is None:
                    return _is_null(right)
                return _if_null(node, _bool_constant(False))
            # Worst case performance, but accurate
            return _if_null(node, ast.And(exprs=[_is_null(left), _is_null(right)], type=_bool_type()))

        # Special optimization for "NotEq" operator
        if node.op in (ast.CompareOperationOp.NotEq, ast.CompareOperationOp.NotLike, ast.CompareOperationOp.NotILike):
            if isinstance(right, ast.Constant):
                if right.value is None:
                    return _is_not_null(left)
                return _if_null(node, _bool_constant(True))
            elif isinstance(left, ast.Constant):
                if left.value is None:
                    return _is_not_null(right)
                return _if_null(node, _bool_constant(True))
            # Worst case performance, but accurate
            return _if_null(node, ast.Or(exprs=[_is_not_null(left), _is_not_null(right)], type=_bool_type()))

        # Return false if one, but only one of the two sides is a null constant
        if isinstance(right, ast.Constant) and right.value is None:
            # Both are a constant null
            if isinstance(left, ast.Constant) and left.value is None:
                return _bool_constant(value_if_both_sides_are_null)

            # Only the right side is null. Return a value only if the left side doesn't matter.
            if value_if_both_sides_are_null == value_if_one_side_is_null:
                return _bool_constant(value_if_one_side_is_null)
        elif isinstance(left, ast.Constant) and left.value is None:
            # Only the left side is null. Return a value only if the right side doesn't matter.
            if value_if_both_sides_are_null == value_if_one_side_is_null:
                return _bool_constant(value_if_one_side_is_null)

        # No constants, so check for nulls in SQL
        if value_if_one_side_is_null is True and value_if_both_sides_are_null is True:
            return _if_null(node, _bool_constant(True))
        elif value_if_one_side_is_null is True and value_if_both_sides_are_null is False:
            return _if_null(node, ast.Or(exprs=[_is_not_null(left), _is_not_null(right)], type=_bool_type()))
        elif value_if_one_side_is_null is False and value_if_both_sides_are_null is True:
            # Worst case performance, but accurate
            return _if_null(node, ast.And(exprs=[_is_null(left), _is_null(right)], type=_bool_type()))
        else:
            return _if_null(node, _bool_constant(False))


def lower_null_semantics(node: _T_AST, context: HogQLContext) -> _T_AST:
    """Make HogQL's two-valued comparison semantics explicit in the AST, so the printer stays mechanical.

    ClickHouse only. Must be the last transform before printing — see the module docstring.
    """
    return cast(_T_AST, NullSemanticsLowering(context).visit(node))
