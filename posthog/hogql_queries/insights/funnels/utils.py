from enum import Enum, auto
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


class SourceTableKind(Enum):
    EVENTS = auto()
    DATA_WAREHOUSE = auto()


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


def is_events_source(source_kind: SourceTableKind) -> bool:
    return source_kind is SourceTableKind.EVENTS


def is_data_warehouse_source(source_kind: SourceTableKind) -> bool:
    return source_kind is SourceTableKind.DATA_WAREHOUSE


def is_events_entity(entity: EntityNode | ExclusionEntityNode) -> TypeGuard[EventsNode | FunnelExclusionEventsNode]:
    return (
        isinstance(entity, EventsNode)
        or isinstance(entity, FunnelExclusionEventsNode)
        or isinstance(entity, ActionsNode)
        or isinstance(entity, FunnelExclusionActionsNode)
    )


def is_data_warehouse_entity(entity: EntityNode | ExclusionEntityNode) -> TypeGuard[DataWarehouseNode]:
    return isinstance(entity, DataWarehouseNode)


def entity_source_mismatch(entity: EntityNode, source_kind: SourceTableKind) -> bool:
    if source_kind is SourceTableKind.EVENTS:
        return not is_events_entity(entity)
    if source_kind is SourceTableKind.DATA_WAREHOUSE:
        return not is_data_warehouse_entity(entity)
    raise ValueError(f"Unknown SourceTableKind: {source_kind}")


def entity_source_or_table_mismatch(entity: EntityNode, source_kind: SourceTableKind, table_name: str) -> bool:
    if entity_source_mismatch(entity, source_kind):
        return True
    if is_events_entity(entity) and table_name != "events":
        return True
    if is_data_warehouse_entity(entity) and table_name != entity.table_name:
        return True
    return False


def get_table_name(entity: EntityNode):
    if is_data_warehouse_entity(entity):
        return entity.table_name
    else:
        return "events"


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
