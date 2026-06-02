from __future__ import annotations

import math
import dataclasses
from typing import cast

from posthog.hogql import ast
from posthog.hogql.base import _T_AST
from posthog.hogql.constants import HogQLDialect
from posthog.hogql.context import HogQLContext
from posthog.hogql.type_system import RuntimeType, parse_sql_runtime_type, runtime_type_from_constant_type
from posthog.hogql.visitor import CloningVisitor

_SAFE_REDUNDANT_CAST_FAMILIES = frozenset({"string", "boolean", "date", "datetime", "uuid"})


def simplify_redundant_type_operations(
    node: _T_AST,
    context: HogQLContext,
    dialect: HogQLDialect,
) -> _T_AST:
    return TypeAwareSimplifier(context=context, dialect=dialect).visit(node)


class TypeAwareSimplifier(CloningVisitor):
    def __init__(self, context: HogQLContext, dialect: HogQLDialect):
        super().__init__(clear_types=False)
        self.context = context
        self.dialect = dialect

    def visit_type_cast(self, node: ast.TypeCast) -> ast.Expr:
        node = cast(ast.TypeCast, super().visit_type_cast(node))
        expr_type = _constant_type(node.expr, self.context)
        if expr_type is None:
            return node

        source_type = runtime_type_from_constant_type(expr_type)
        target_type = parse_sql_runtime_type(node.type_name, dialect=self.dialect)
        if _is_redundant_cast(source_type=source_type, target_type=target_type):
            return node.expr
        return node

    def visit_arithmetic_operation(self, node: ast.ArithmeticOperation) -> ast.Expr:
        node = cast(ast.ArithmeticOperation, super().visit_arithmetic_operation(node))
        return _fold_numeric_arithmetic_operation(node, self.context) or node

    def visit_call(self, node: ast.Call) -> ast.Expr:
        node = cast(ast.Call, super().visit_call(node))
        normalized_name = node.name.lower()

        if normalized_name in {"assumenotnull", "tonullable"}:
            return self._simplify_nullability_call(node, normalized_name)

        if normalized_name in {"ifnull", "coalesce"}:
            return self._simplify_null_fallback_call(node, normalized_name)

        if len(node.args) != 1:
            return node

        arg_type = _constant_type(node.args[0], self.context)
        if arg_type is None:
            return node

        source_type = runtime_type_from_constant_type(arg_type)
        target_type = _conversion_call_target_type(normalized_name, source_type)
        if target_type is not None and _is_redundant_cast(source_type=source_type, target_type=target_type):
            return node.args[0]

        return node

    def _simplify_nullability_call(self, node: ast.Call, normalized_name: str) -> ast.Expr:
        if len(node.args) != 1:
            return node

        arg_type = _constant_type(node.args[0], self.context)
        if arg_type is None or isinstance(arg_type, ast.UnknownType):
            return node

        if normalized_name == "assumenotnull" and not arg_type.nullable:
            return node.args[0]
        if normalized_name == "tonullable" and arg_type.nullable:
            return node.args[0]
        return node

    def _simplify_null_fallback_call(self, node: ast.Call, normalized_name: str) -> ast.Expr:
        if not node.args:
            return node

        first_arg_type = _constant_type(node.args[0], self.context)
        if first_arg_type is None or isinstance(first_arg_type, ast.UnknownType) or first_arg_type.nullable:
            return node

        if normalized_name == "ifnull" and len(node.args) == 2:
            return node.args[0]
        if normalized_name == "coalesce":
            return node.args[0]
        return node


def _constant_type(node: ast.Expr, context: HogQLContext) -> ast.ConstantType | None:
    if node.type is None:
        return None
    return node.type.resolve_constant_type(context)


def _conversion_call_target_type(normalized_name: str, source_type: RuntimeType) -> RuntimeType | None:
    if normalized_name == "tostring" and source_type.family == "string":
        return dataclasses.replace(source_type, family="string")
    if normalized_name == "todate" and source_type.family == "date":
        return dataclasses.replace(source_type, family="date")
    if normalized_name == "todatetime" and source_type.family == "datetime":
        return dataclasses.replace(source_type, family="datetime")
    if normalized_name == "tobool" and source_type.family == "boolean":
        return dataclasses.replace(source_type, family="boolean")
    return None


def _fold_numeric_arithmetic_operation(node: ast.ArithmeticOperation, context: HogQLContext) -> ast.Constant | None:
    if not isinstance(node.left, ast.Constant) or not isinstance(node.right, ast.Constant):
        return None

    if not _is_numeric_literal(node.left.value) or not _is_numeric_literal(node.right.value):
        return None

    left_type = _constant_type(node.left, context)
    right_type = _constant_type(node.right, context)
    if left_type is None or right_type is None:
        return None

    left_runtime_type = runtime_type_from_constant_type(left_type)
    right_runtime_type = runtime_type_from_constant_type(right_type)
    if left_runtime_type.family not in {"integer", "float"} or right_runtime_type.family not in {"integer", "float"}:
        return None
    if left_runtime_type.nullable or right_runtime_type.nullable:
        return None

    result = _evaluate_numeric_arithmetic(node.op, node.left.value, node.right.value)
    if result is None:
        return None

    return ast.Constant(value=result, type=_constant_type_from_literal(result), start=node.start, end=node.end)


def _evaluate_numeric_arithmetic(
    op: ast.ArithmeticOperationOp,
    left: int | float,
    right: int | float,
) -> int | float | None:
    if op == ast.ArithmeticOperationOp.Add:
        result = left + right
    elif op == ast.ArithmeticOperationOp.Sub:
        result = left - right
    elif op == ast.ArithmeticOperationOp.Mult:
        result = left * right
    elif op == ast.ArithmeticOperationOp.Div:
        if right == 0:
            return None
        result = left / right
    elif op == ast.ArithmeticOperationOp.Mod:
        if right == 0:
            return None
        result = left % right
    else:
        return None

    if isinstance(result, float) and not math.isfinite(result):
        return None
    return result


def _is_numeric_literal(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _constant_type_from_literal(value: int | float) -> ast.ConstantType:
    if isinstance(value, int):
        return ast.IntegerType(nullable=False)
    return ast.FloatType(nullable=False)


def _is_redundant_cast(source_type: RuntimeType, target_type: RuntimeType) -> bool:
    if source_type.family == "unknown" or target_type.family == "unknown":
        return False
    if source_type.family != target_type.family:
        return False
    if source_type.family not in _SAFE_REDUNDANT_CAST_FAMILIES:
        return False
    if source_type.nullable != target_type.nullable:
        return False
    if source_type.family == "datetime" and (
        source_type.precision != target_type.precision or source_type.timezone != target_type.timezone
    ):
        return False
    return True
