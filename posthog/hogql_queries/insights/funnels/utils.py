from typing import TypeGuard

from rest_framework.exceptions import ValidationError

from posthog.schema import (
    ActionsNode,
    DataWarehouseNode,
    EventsNode,
    FunnelConversionWindowTimeUnit,
    FunnelExclusionActionsNode,
    FunnelExclusionEventsNode,
)

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr

from posthog.constants import FUNNEL_WINDOW_INTERVAL_TYPES
from posthog.types import EntityNode, ExclusionEntityNode


def funnel_window_interval_unit_to_sql(
    funnelWindowIntervalUnit: FunnelConversionWindowTimeUnit | None,
) -> FUNNEL_WINDOW_INTERVAL_TYPES:
    if funnelWindowIntervalUnit is None:
        return "DAY"
    elif funnelWindowIntervalUnit == "second":
        return "SECOND"
    elif funnelWindowIntervalUnit == "minute":
        return "MINUTE"
    elif funnelWindowIntervalUnit == "hour":
        return "HOUR"
    elif funnelWindowIntervalUnit == "week":
        return "WEEK"
    elif funnelWindowIntervalUnit == "month":
        return "MONTH"
    elif funnelWindowIntervalUnit == "day":
        return "DAY"
    else:
        raise ValidationError(f"{funnelWindowIntervalUnit} not supported")


def get_breakdown_expr(
    breakdowns: list[str | int] | str | int, properties_column: str | None, normalize_url: bool | None = False
) -> ast.Expr:
    def make_field(breakdown: str | int) -> ast.Expr:
        if properties_column is None:
            # breakdown already refers to a top-level field
            return ast.Field(chain=[breakdown])
        else:
            return ast.Field(chain=[*properties_column.split("."), breakdown])

    if isinstance(breakdowns, str) or isinstance(breakdowns, int) or breakdowns is None:
        return ast.Call(
            name="ifNull",
            args=[
                ast.Call(name="toString", args=[make_field(breakdowns)]),
                ast.Constant(value=""),
            ],
        )
    else:
        exprs = []
        for breakdown in breakdowns:
            expr: ast.Expr = ast.Call(
                name="ifNull",
                args=[
                    ast.Call(name="toString", args=[make_field(breakdown)]),
                    ast.Constant(value=""),
                ],
            )
            if normalize_url:
                regex = "[\\\\/?#]*$"
                expr = parse_expr(
                    f"if( empty( replaceRegexpOne({{breakdown_value}}, '{regex}', '') ), '/', replaceRegexpOne({{breakdown_value}}, '{regex}', ''))",
                    {"breakdown_value": expr},
                )
            exprs.append(expr)
        expression = ast.Array(exprs=exprs)

    return expression


def is_events_entity(entity: EntityNode | ExclusionEntityNode) -> TypeGuard[EventsNode | FunnelExclusionEventsNode]:
    return (
        isinstance(entity, EventsNode)
        or isinstance(entity, FunnelExclusionEventsNode)
        or isinstance(entity, ActionsNode)
        or isinstance(entity, FunnelExclusionActionsNode)
    )


def is_data_warehouse_entity(entity: EntityNode | ExclusionEntityNode) -> TypeGuard[DataWarehouseNode]:
    return isinstance(entity, DataWarehouseNode)


def data_warehouse_config_key(node: DataWarehouseNode) -> tuple[str, str, str]:
    return (
        node.id_field,
        node.distinct_id_field,
        node.timestamp_field,
    )


def entity_config_mismatch(step_entity: EntityNode, table_entity: EntityNode | None) -> bool:
    if isinstance(step_entity, DataWarehouseNode) != isinstance(table_entity, DataWarehouseNode):
        return True

    if not isinstance(step_entity, DataWarehouseNode):
        return False

    assert isinstance(table_entity, DataWarehouseNode)
    return data_warehouse_config_key(step_entity) != data_warehouse_config_key(table_entity)


def alias_columns_in_select(columns: list[ast.Expr], table_alias: str) -> list[ast.Expr]:
    """
    Returns a list of `column_or_alias_name AS table_alias.column_or_alias_name`, from a given list of `columns`.
    """
    result: list[ast.Expr] = []
    for col in columns:
        if isinstance(col, ast.Alias):
            result.append(ast.Alias(alias=col.alias, expr=ast.Field(chain=[table_alias, col.alias])))
        elif isinstance(col, ast.Field):
            # assumes the last chain part is the column name
            column_name = col.chain[-1]
            if not isinstance(column_name, str):
                raise ValueError(f"Cannot alias field with chain {col.chain!r}")
            result.append(ast.Alias(alias=column_name, expr=ast.Field(chain=[table_alias, column_name])))
        else:
            raise ValueError(f"Unexpected select expression {col!r}")
    return result
