from __future__ import annotations

import json
import math
from datetime import date, datetime, timedelta
from typing import cast
from uuid import UUID

from posthog.hogql import ast
from posthog.hogql.base import _T_AST
from posthog.hogql.constants import HogQLDialect
from posthog.hogql.context import HogQLContext
from posthog.hogql.observability import record_type_simplification
from posthog.hogql.type_system import (
    RuntimeType,
    constant_type_from_runtime_type,
    parse_sql_runtime_type,
    runtime_type_from_constant_type,
)
from posthog.hogql.visitor import CloningVisitor

_SAFE_REDUNDANT_CAST_FAMILIES = frozenset({"string", "boolean", "date", "datetime", "uuid"})


def simplify_redundant_type_operations(
    node: _T_AST,
    context: HogQLContext,
    dialect: HogQLDialect,
) -> _T_AST:
    return TypeAwareSimplifier(context=context, dialect=dialect).visit(node)


def simplify_argmax_over_non_nullable(node: _T_AST, context: HogQLContext) -> _T_AST:
    """Rewrite ``tupleElement(argMax(tuple(X), V), 1)`` to ``argMax(X, V)`` when X can't be NULL.

    ``argmax_select`` wraps every argMax in ``tuple()``/``tupleElement()`` so a NULL value in the
    latest (max-version) row still wins — plain ClickHouse ``argMax`` skips NULLs and would return a
    stale earlier value instead. A non-nullable column has no NULL to skip, so the wrap is pure
    overhead and plain ``argMax`` is exactly equivalent. Runs after lazy-table expansion and property
    swapping, so the inner expression is in its final form (column or JSON extract) with a resolved,
    trustworthy nullability.
    """
    return _ArgMaxTupleSimplifier(context).visit(node)


class _ArgMaxTupleSimplifier(CloningVisitor):
    def __init__(self, context: HogQLContext):
        super().__init__(clear_types=False)
        self.context = context

    def visit_call(self, node: ast.Call) -> ast.Expr:
        node = cast(ast.Call, super().visit_call(node))
        if node.name != "tupleElement" or len(node.args) != 2:
            return node
        if not (isinstance(node.args[1], ast.Constant) and node.args[1].value == 1):
            return node
        argmax = node.args[0]
        if not (isinstance(argmax, ast.Call) and argmax.name == "argMax" and len(argmax.args) == 2):
            return node
        tuple_call = argmax.args[0]
        if not (isinstance(tuple_call, ast.Call) and tuple_call.name == "tuple" and len(tuple_call.args) == 1):
            return node
        inner = tuple_call.args[0]
        inner_type = _constant_type(inner, self.context)
        if inner_type is None or isinstance(inner_type, ast.UnknownType) or inner_type.nullable:
            return node
        # Carry every field off the original argMax (params, distinct, FILTER, etc.) so a future caller's clause is not silently dropped; argmax_select sets none today.
        return ast.Call(
            name="argMax",
            args=[inner, argmax.args[1]],
            params=argmax.params,
            distinct=argmax.distinct,
            within_group=argmax.within_group,
            order_by=argmax.order_by,
            filter_expr=argmax.filter_expr,
            type=node.type,
            start=node.start,
            end=node.end,
        )


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
            self._record("redundant_cast")
            return node.expr
        folded_constant = _fold_constant_cast(node.expr, target_type, allow_numeric=False)
        if folded_constant is not None:
            self._record("constant_fold")
            return folded_constant
        return node

    def visit_arithmetic_operation(self, node: ast.ArithmeticOperation) -> ast.Expr:
        node = cast(ast.ArithmeticOperation, super().visit_arithmetic_operation(node))
        folded = _fold_numeric_arithmetic_operation(node, self.context) or _fold_temporal_interval_arithmetic_operation(
            node
        )
        if folded is not None:
            self._record("constant_fold")
            return folded
        return node

    def visit_call(self, node: ast.Call) -> ast.Expr:
        node = cast(ast.Call, super().visit_call(node))
        normalized_name = node.name.lower()

        if normalized_name in {"assumenotnull", "tonullable"}:
            simplified = self._simplify_nullability_call(node, normalized_name)
            if simplified is not node:
                self._record("nullability_wrapper")
            return simplified

        if normalized_name in {"ifnull", "coalesce"}:
            simplified = self._simplify_null_fallback_call(node, normalized_name)
            if simplified is not node:
                self._record("null_fallback")
            return simplified

        folded_json = _fold_literal_json_call(node, self.dialect)
        if folded_json is not None:
            self._record("json_fold")
            return folded_json

        folded_conversion = _fold_constant_conversion_call(node, self.dialect)
        if folded_conversion is not None:
            self._record("constant_fold")
            return folded_conversion

        if len(node.args) != 1:
            return node

        arg_type = _constant_type(node.args[0], self.context)
        if arg_type is None:
            return node

        source_type = runtime_type_from_constant_type(arg_type)
        target_type = _conversion_call_target_type(normalized_name, source_type)
        if target_type is not None and _is_redundant_cast(source_type=source_type, target_type=target_type):
            self._record("redundant_cast")
            return node.args[0]

        return node

    def _record(self, kind: str) -> None:
        record_type_simplification(self.dialect, kind)

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

        if normalized_name == "ifnull" and len(node.args) == 2:
            if _is_null_constant(node.args[0]):
                return node.args[1]
            if _is_null_constant(node.args[1]):
                return node.args[0]

        if normalized_name == "coalesce":
            non_null_args = [arg for arg in node.args if not _is_null_constant(arg)]
            if len(non_null_args) != len(node.args):
                if not non_null_args:
                    return ast.Constant(value=None, type=ast.UnknownType(), start=node.start, end=node.end)
                if len(non_null_args) == 1:
                    return non_null_args[0]
                return ast.Call(
                    name=node.name,
                    args=non_null_args,
                    params=node.params,
                    distinct=node.distinct,
                    type=node.type,
                    start=node.start,
                    end=node.end,
                )

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


_CONVERSION_CALL_TARGET_FAMILIES = {
    "tostring": "string",
    "todate": "date",
    "todatetime": "datetime",
    "tobool": "boolean",
}


def _conversion_call_target_type(normalized_name: str, source_type: RuntimeType) -> RuntimeType | None:
    if _CONVERSION_CALL_TARGET_FAMILIES.get(normalized_name) == source_type.family:
        return source_type
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

    if isinstance(result, float) and not math.isfinite(result):
        return None
    return result


def _is_numeric_literal(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _constant_type_from_literal(value: int | float) -> ast.ConstantType:
    if isinstance(value, int):
        return ast.IntegerType(nullable=False)
    return ast.FloatType(nullable=False)


def _fold_temporal_interval_arithmetic_operation(node: ast.ArithmeticOperation) -> ast.Constant | None:
    if node.op not in {ast.ArithmeticOperationOp.Add, ast.ArithmeticOperationOp.Sub}:
        return None

    left_date = node.left.value if isinstance(node.left, ast.Constant) and isinstance(node.left.value, date) else None
    right_date = (
        node.right.value if isinstance(node.right, ast.Constant) and isinstance(node.right.value, date) else None
    )
    left_delta = _constant_day_or_week_interval(node.left)
    right_delta = _constant_day_or_week_interval(node.right)

    result: date | datetime | None = None
    if left_date is not None and right_delta is not None:
        result = left_date + right_delta if node.op == ast.ArithmeticOperationOp.Add else left_date - right_delta
    elif node.op == ast.ArithmeticOperationOp.Add and left_delta is not None and right_date is not None:
        result = right_date + left_delta

    if result is None:
        return None

    if isinstance(result, datetime):
        constant_type: ast.ConstantType = ast.DateTimeType(nullable=False)
    else:
        constant_type = ast.DateType(nullable=False)
    return ast.Constant(value=result, type=constant_type, start=node.start, end=node.end)


def _constant_day_or_week_interval(node: ast.Expr) -> timedelta | None:
    if not isinstance(node, ast.Call) or len(node.args) != 1:
        return None

    interval_value = node.args[0].value if isinstance(node.args[0], ast.Constant) else None
    if not isinstance(interval_value, int) or isinstance(interval_value, bool):
        return None

    normalized_name = node.name.lower()
    if normalized_name == "tointervalday":
        return timedelta(days=interval_value)
    if normalized_name == "tointervalweek":
        return timedelta(weeks=interval_value)
    return None


def _is_null_constant(node: ast.Expr) -> bool:
    return isinstance(node, ast.Constant) and node.value is None


def _fold_constant_conversion_call(node: ast.Call, dialect: HogQLDialect) -> ast.Constant | None:
    normalized_name = node.name.lower()
    if normalized_name in {"accuratecast", "accuratecastornull"}:
        if len(node.args) != 2:
            return None
        target_type_name = _constant_string_value(node.args[1])
        if target_type_name is None:
            return None
        target_type = parse_sql_runtime_type(target_type_name, dialect=dialect)
        return _fold_constant_cast(node.args[0], target_type)

    if len(node.args) != 1:
        return None

    source = node.args[0]
    if (
        normalized_name in {"toint", "tointorzero"}
        or normalized_name.startswith("_toint")
        or normalized_name.startswith("_touint")
    ):
        return _fold_constant_cast(source, parse_sql_runtime_type("Int64", dialect=dialect))
    if normalized_name in {"tofloat", "tofloatorzero", "tofloatordefault"}:
        return _fold_constant_cast(source, parse_sql_runtime_type("Float64", dialect=dialect))
    if normalized_name in {"todate", "to_date", "_todate"}:
        return _fold_constant_cast(source, parse_sql_runtime_type("Date", dialect=dialect))
    if normalized_name == "tobool":
        return _fold_constant_cast(source, parse_sql_runtime_type("Bool", dialect=dialect))
    if normalized_name == "touuid":
        return _fold_constant_cast(source, parse_sql_runtime_type("UUID", dialect=dialect))
    return None


def _fold_constant_cast(source: ast.Expr, target_type: RuntimeType, allow_numeric: bool = True) -> ast.Constant | None:
    if not isinstance(source, ast.Constant) or source.value is None or target_type.family == "unknown":
        return None
    if not allow_numeric and target_type.family in {"integer", "float", "decimal"}:
        return None

    converted_value = _convert_literal_to_runtime_type(source.value, target_type)
    if converted_value is None:
        return None

    constant_type = constant_type_from_runtime_type(target_type.with_nullable(False))
    return ast.Constant(value=converted_value, type=constant_type, start=source.start, end=source.end)


def _convert_literal_to_runtime_type(value: object, target_type: RuntimeType) -> object | None:
    try:
        if target_type.family == "integer":
            if isinstance(value, bool):
                return None
            if isinstance(value, int):
                return value
            if isinstance(value, str):
                return int(value)
            return None
        if target_type.family == "float":
            if isinstance(value, bool):
                return None
            if isinstance(value, (int, float, str)):
                result = float(value)
                return result if math.isfinite(result) else None
            return None
        if target_type.family == "boolean":
            if isinstance(value, bool):
                return value
            if isinstance(value, int) and value in (0, 1):
                return bool(value)
            if isinstance(value, str) and value.lower() in {"true", "false"}:
                return value.lower() == "true"
            return None
        if target_type.family == "uuid":
            if isinstance(value, UUID):
                return value
            if isinstance(value, str):
                return UUID(value)
            return None
        if target_type.family == "date":
            if isinstance(value, datetime):
                return value.date()
            if isinstance(value, date):
                return value
            if isinstance(value, str):
                return date.fromisoformat(value)
            return None
    except (TypeError, ValueError, OverflowError):
        return None
    return None


def _fold_literal_json_call(node: ast.Call, dialect: HogQLDialect) -> ast.Constant | None:
    normalized_name = node.name.lower()
    if normalized_name not in {
        "jsonextract",
        "jsonextractuint",
        "jsonextractint",
        "jsonextractfloat",
        "jsonextractbool",
        "jsonextractstring",
        "jsonextractraw",
        "jsonhas",
        "jsonlength",
        "jsonarraylength",
    }:
        return None
    if not node.args:
        return None

    raw_json = _constant_string_value(node.args[0])
    if raw_json is None:
        return None

    try:
        document = json.loads(raw_json)
    except json.JSONDecodeError:
        return None

    if normalized_name == "jsonextract":
        if len(node.args) < 2:
            return None
        type_name = _constant_string_value(node.args[-1])
        if type_name is None:
            return None
        target_type = parse_sql_runtime_type(type_name, dialect=dialect)
        path_args = node.args[1:-1]
    else:
        target_type = None
        path_args = node.args[1:]

    path = [_constant_json_path_component(arg) for arg in path_args]
    if any(component is None for component in path):
        return None

    path_value = _literal_json_path_value(document, cast(list[str | int], path))
    if path_value is _JSON_PATH_MISSING:
        return None

    if normalized_name == "jsonhas":
        return ast.Constant(value=1, type=ast.IntegerType(nullable=False), start=node.start, end=node.end)

    if normalized_name in {"jsonlength", "jsonarraylength"}:
        if isinstance(path_value, (dict, list)):
            return ast.Constant(
                value=len(path_value), type=ast.IntegerType(nullable=False), start=node.start, end=node.end
            )
        return None

    if normalized_name == "jsonextractraw":
        return ast.Constant(
            value=json.dumps(path_value, separators=(",", ":")),
            type=ast.StringType(nullable=False),
            start=node.start,
            end=node.end,
        )

    if normalized_name == "jsonextractstring":
        if isinstance(path_value, str):
            return ast.Constant(value=path_value, type=ast.StringType(nullable=False), start=node.start, end=node.end)
        return None

    if normalized_name in {"jsonextractuint", "jsonextractint"}:
        if isinstance(path_value, int) and not isinstance(path_value, bool):
            return ast.Constant(value=path_value, type=ast.IntegerType(nullable=False), start=node.start, end=node.end)
        return None

    if normalized_name == "jsonextractfloat":
        if isinstance(path_value, (int, float)) and not isinstance(path_value, bool):
            return ast.Constant(
                value=float(path_value), type=ast.FloatType(nullable=False), start=node.start, end=node.end
            )
        return None

    if normalized_name == "jsonextractbool":
        if isinstance(path_value, bool):
            return ast.Constant(value=path_value, type=ast.BooleanType(nullable=False), start=node.start, end=node.end)
        return None

    if normalized_name == "jsonextract" and target_type is not None:
        converted_value = _convert_json_literal_to_runtime_type(path_value, target_type)
        if converted_value is None:
            return None
        return ast.Constant(
            value=converted_value,
            type=constant_type_from_runtime_type(target_type.with_nullable(False)),
            start=node.start,
            end=node.end,
        )

    return None


_JSON_PATH_MISSING = object()


def _literal_json_path_value(document: object, path: list[str | int]) -> object:
    current = document
    for component in path:
        if isinstance(current, dict) and isinstance(component, str) and component in current:
            current = current[component]
        elif isinstance(current, list) and isinstance(component, int) and 0 <= component < len(current):
            current = current[component]
        else:
            return _JSON_PATH_MISSING
    return current


def _convert_json_literal_to_runtime_type(value: object, target_type: RuntimeType) -> object | None:
    if target_type.family == "string":
        return value if isinstance(value, str) else None
    if target_type.family == "integer":
        return value if isinstance(value, int) and not isinstance(value, bool) else None
    if target_type.family == "float":
        return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None
    if target_type.family == "boolean":
        return value if isinstance(value, bool) else None
    if target_type.family == "array":
        return value if isinstance(value, list) else None
    if target_type.family == "map":
        return value if isinstance(value, dict) else None
    return None


def _constant_string_value(node: ast.Expr) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _constant_json_path_component(node: ast.Expr) -> str | int | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, (str, int)) and not isinstance(node.value, bool):
        return node.value
    return None


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
