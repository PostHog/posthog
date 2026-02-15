from __future__ import annotations

from typing import TYPE_CHECKING, Optional, Union

from posthog.schema import (
    ActionsNode,
    BaseMathType,
    BreakdownType,
    DataWarehouseNode,
    EventsNode,
    GroupNode,
    MultipleBreakdownType,
)

from posthog.hogql import ast
from posthog.hogql.property import action_to_expr, property_to_expr

from posthog.constants import UNIQUE_GROUPS

if TYPE_CHECKING:
    from posthog.models import Team


def get_properties_chain(
    breakdown_type: BreakdownType | MultipleBreakdownType | None,
    breakdown_field: str,
    group_type_index: Optional[float | int],
) -> list[str | int]:
    if breakdown_type == "person":
        if breakdown_field.startswith("$virt_"):
            # Virtual properties exist as expression fields on the persons table
            return ["person", breakdown_field]
        else:
            return ["person", "properties", breakdown_field]

    if breakdown_type == "session":
        return ["session", breakdown_field]

    if breakdown_type == "group" and group_type_index is not None:
        group_type_index_int = int(group_type_index)
        if breakdown_field.startswith("$virt_"):
            # Virtual properties exist as expression fields on the groups table
            return [f"group_{group_type_index_int}", breakdown_field]
        else:
            return [f"group_{group_type_index_int}", "properties", breakdown_field]
    elif breakdown_type == "group" and group_type_index is None:
        raise Exception("group_type_index missing from params")

    if breakdown_type == "data_warehouse":
        return [*breakdown_field.split(".")]

    if breakdown_type == "data_warehouse_person_property":
        return ["person", *breakdown_field.split(".")]

    return ["properties", breakdown_field]


def is_groups_math(series: Union[EventsNode, ActionsNode, DataWarehouseNode | GroupNode]) -> bool:
    return (
        series.math in {BaseMathType.DAU, UNIQUE_GROUPS, BaseMathType.WEEKLY_ACTIVE, BaseMathType.MONTHLY_ACTIVE}
        and series.math_group_type_index is not None
    )


def group_node_to_expr(group: GroupNode, team: Team) -> ast.Expr | None:
    from posthog.models import Action

    group_filters: list[ast.Expr] = []
    for node in group.nodes:
        if isinstance(node, EventsNode):
            if node.event is None:
                continue
            node_expr: ast.Expr = ast.CompareOperation(
                op=ast.CompareOperationOp.Eq,
                left=ast.Field(chain=["event"]),
                right=ast.Constant(value=str(node.event)),
            )
            if node.properties is not None and node.properties != []:
                node_expr = ast.And(exprs=[node_expr, property_to_expr(node.properties, team)])
            group_filters.append(node_expr)
        elif isinstance(node, ActionsNode):
            try:
                action = Action.objects.get(pk=int(node.id), team__project_id=team.project_id)
                node_expr = action_to_expr(action)
                if node.properties is not None and node.properties != []:
                    node_expr = ast.And(exprs=[node_expr, property_to_expr(node.properties, team)])
                group_filters.append(node_expr)
            except Action.DoesNotExist:
                pass

    if len(group_filters) == 0:
        return None

    if len(group_filters) == 1:
        return group_filters[0]

    if group.operator == "OR":
        return ast.Or(exprs=group_filters)

    if group.operator == "AND":
        return ast.And(exprs=group_filters)

    return None
