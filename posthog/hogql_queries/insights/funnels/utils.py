from typing import TypeIs

from rest_framework.exceptions import ValidationError

from posthog.schema import (
    ActionsNode,
    EventsNode,
    FunnelConversionWindowTimeUnit,
    FunnelExclusionActionsNode,
    FunnelExclusionEventsNode,
    FunnelsDataWarehouseNode,
)

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr
from posthog.hogql.property import apply_path_cleaning

from posthog.constants import FUNNEL_WINDOW_INTERVAL_TYPES
from posthog.hogql_queries.insights.utils.breakdowns import ALL_USERS_COHORT_ID, NOT_IN_COHORT_ID
from posthog.models.team.team import Team
from posthog.types import FunnelEntityNode, FunnelExclusionEntityNode

from products.cohorts.backend.models.cohort import Cohort


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
    breakdowns: list[str | int] | str | int,
    properties_column: str | None,
    normalize_url: bool | None = False,
    path_cleaning: bool | None = False,
    team: Team | None = None,
) -> ast.Expr:
    def make_field(breakdown: str | int) -> ast.Expr:
        if properties_column is None:
            # breakdown already refers to a top-level field
            return ast.Field(chain=[breakdown])
        else:
            return ast.Field(chain=[*properties_column.split("."), breakdown])

    # Fail loudly rather than silently skipping cleaning if a caller forgets the team
    if path_cleaning and team is None:
        raise ValueError("get_breakdown_expr: path_cleaning=True requires a team")

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
            if path_cleaning and team is not None:
                expr = apply_path_cleaning(expr, team)
            if normalize_url:
                regex = "[\\\\/?#]*$"
                expr = parse_expr(
                    f"if( empty( replaceRegexpOne({{breakdown_value}}, '{regex}', '') ), '/', replaceRegexpOne({{breakdown_value}}, '{regex}', ''))",
                    {"breakdown_value": expr},
                )
            exprs.append(expr)
        expression = ast.Array(exprs=exprs)

    return expression


def is_events_entity(
    entity: FunnelEntityNode | FunnelExclusionEntityNode | None,
) -> TypeIs[EventsNode | FunnelExclusionEventsNode]:
    return (
        isinstance(entity, EventsNode)
        or isinstance(entity, FunnelExclusionEventsNode)
        or isinstance(entity, ActionsNode)
        or isinstance(entity, FunnelExclusionActionsNode)
    )


def data_warehouse_config_key(node: FunnelsDataWarehouseNode) -> tuple[str, str, str, str]:
    return (
        node.table_name,
        node.id_field,
        node.aggregation_target_field,
        node.timestamp_field,
    )


def entity_config_mismatch(step_entity: FunnelEntityNode, table_entity: FunnelEntityNode | None) -> bool:
    if isinstance(step_entity, FunnelsDataWarehouseNode) != isinstance(table_entity, FunnelsDataWarehouseNode):
        return True

    if not isinstance(step_entity, FunnelsDataWarehouseNode):
        return False

    assert table_entity is not None and isinstance(table_entity, FunnelsDataWarehouseNode)
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


def get_breakdown_cohort_name(cohort_id: int, team: Team, not_in_cohort_name: str | None = None) -> str:
    if cohort_id == ALL_USERS_COHORT_ID:
        return "all users"
    elif cohort_id == NOT_IN_COHORT_ID:
        if not_in_cohort_name:
            return f"Not in {not_in_cohort_name}"
        return "Not in cohort"
    else:
        cohort_name = Cohort.objects.get(pk=cohort_id, team__project_id=team.project_id).name
        return cohort_name or ""
