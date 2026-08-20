from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from posthog.hogql import ast

type LocalValue = None | int | float | str | list[LocalValue] | tuple[LocalValue, ...]


@dataclass(frozen=True)
class LocalQueryResult:
    results: list[tuple[LocalValue, ...]]
    types: list[tuple[str, str]]


@dataclass(frozen=True)
class _TypedValue:
    value: LocalValue
    clickhouse_type: str


class _UnsupportedLocalQuery(Exception):
    pass


def try_execute_local_constant_query(query: ast.SelectQuery, columns: list[str]) -> LocalQueryResult | None:
    try:
        return _execute_local_constant_query(query, columns)
    except _UnsupportedLocalQuery:
        return None


def _execute_local_constant_query(query: ast.SelectQuery, columns: list[str]) -> LocalQueryResult:
    if not _is_supported_select(query) or len(query.select) != len(columns):
        raise _UnsupportedLocalQuery

    values = [_evaluate_expression(expression) for expression in query.select]
    types = [(column, value.clickhouse_type) for column, value in zip(columns, values, strict=True)]

    include_row = _evaluate_where(query.where)
    limit = _evaluate_row_count(query.limit, default=1)
    offset = _evaluate_row_count(query.offset, default=0)
    results = [tuple(value.value for value in values)] if include_row and limit != 0 and offset == 0 else []

    return LocalQueryResult(results=results, types=types)


def _is_supported_select(query: ast.SelectQuery) -> bool:
    return (
        query.ctes is None
        and query.distinct is None
        and query.select_from is None
        and query.array_join_op is None
        and query.array_join_list is None
        and query.window_exprs is None
        and query.prewhere is None
        and query.having is None
        and query.qualify is None
        and query.group_by is None
        and query.group_by_mode is None
        and query.order_by is None
        and query.interpolate is None
        and query.limit_by is None
        and query.limit_with_ties is None
        and query.limit_percent is None
        and query.settings is None
        and query.view_name is None
    )


def _evaluate_expression(expression: ast.Expr) -> _TypedValue:
    if isinstance(expression, ast.Alias):
        return _evaluate_expression(expression.expr)
    if isinstance(expression, ast.Constant):
        return _evaluate_constant(expression.value)
    if isinstance(expression, ast.Array):
        return _evaluate_array(expression)
    if isinstance(expression, ast.Tuple):
        values = [_evaluate_expression(item) for item in expression.exprs]
        return _TypedValue(
            value=tuple(value.value for value in values),
            clickhouse_type=f"Tuple({', '.join(value.clickhouse_type for value in values)})",
        )
    raise _UnsupportedLocalQuery


def _evaluate_constant(value: object) -> _TypedValue:
    if value is None:
        return _TypedValue(value=None, clickhouse_type="Nullable(Nothing)")
    if type(value) is bool:
        return _TypedValue(value=int(value), clickhouse_type="UInt8")
    if type(value) is int:
        return _TypedValue(value=value, clickhouse_type=_integer_type(value))
    if type(value) is float:
        return _TypedValue(value=value, clickhouse_type="Float64")
    if type(value) is str:
        return _TypedValue(value=value, clickhouse_type="String")
    raise _UnsupportedLocalQuery


def _integer_type(value: int) -> str:
    if value >= 0:
        for bits in (8, 16, 32, 64):
            if value <= 2**bits - 1:
                return f"UInt{bits}"
    else:
        for bits in (8, 16, 32, 64):
            if -(2 ** (bits - 1)) <= value:
                return f"Int{bits}"
    raise _UnsupportedLocalQuery


def _evaluate_array(expression: ast.Array) -> _TypedValue:
    values = [_evaluate_expression(item) for item in expression.exprs]
    if not values:
        return _TypedValue(value=[], clickhouse_type="Array(Nothing)")

    non_null_values = [value for value in values if value.value is not None]
    if not non_null_values:
        element_type = "Nullable(Nothing)"
    else:
        element_type = _common_array_type(non_null_values)
        if len(non_null_values) != len(values):
            element_type = f"Nullable({element_type})"

    return _TypedValue(
        value=[value.value for value in values],
        clickhouse_type=f"Array({element_type})",
    )


def _common_array_type(values: list[_TypedValue]) -> str:
    if all(type(value.value) is int for value in values):
        integers = [cast(int, value.value) for value in values]
        return _integer_type_for_range(min(integers), max(integers))

    first_type = values[0].clickhouse_type
    if all(value.clickhouse_type == first_type for value in values):
        return first_type
    raise _UnsupportedLocalQuery


def _integer_type_for_range(minimum: int, maximum: int) -> str:
    if minimum >= 0:
        return _integer_type(maximum)
    for bits in (8, 16, 32, 64):
        if -(2 ** (bits - 1)) <= minimum and maximum <= 2 ** (bits - 1) - 1:
            return f"Int{bits}"
    raise _UnsupportedLocalQuery


def _evaluate_where(expression: ast.Expr | None) -> bool:
    if expression is None:
        return True
    value = _evaluate_expression(expression)
    if value.clickhouse_type != "UInt8" or type(value.value) is not int:
        raise _UnsupportedLocalQuery
    return value.value != 0


def _evaluate_row_count(expression: ast.Expr | None, *, default: int) -> int:
    if expression is None:
        return default
    if not isinstance(expression, ast.Constant) or type(expression.value) is not int or expression.value < 0:
        raise _UnsupportedLocalQuery
    return expression.value
