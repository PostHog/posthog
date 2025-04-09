from posthog.hogql import ast
from posthog.hogql.property import action_to_expr, property_to_expr
from posthog.models.action.action import Action
from posthog.models.team.team import Team
from posthog.schema import (
    ActionsNode,
    CohortPropertyFilter,
    DataWarehouseNode,
    EmptyPropertyFilter,
    EventsNode,
    FunnelExclusionActionsNode,
    FunnelExclusionEventsNode,
    HogQLPropertyFilter,
)
from posthog.types import AnyPropertyFilter, EntityNode, ExclusionEntityNode
from collections import Counter


def is_equal_type(a: EntityNode, b: EntityNode | ExclusionEntityNode) -> bool:
    if isinstance(a, EventsNode):
        return isinstance(b, EventsNode) or isinstance(b, FunnelExclusionEventsNode)
    if isinstance(a, ActionsNode):
        return isinstance(b, ActionsNode) or isinstance(b, FunnelExclusionActionsNode)
    if isinstance(a, DataWarehouseNode):
        return isinstance(b, DataWarehouseNode)
    raise ValueError(detail=f"Type comparison for {type(a)} and {type(b)} not implemented.")


def is_equal(a: EntityNode, b: EntityNode | ExclusionEntityNode, compare_properties=True) -> bool:
    """Checks if two entities are semantically equal."""

    # different type
    if not is_equal_type(a, b):
        return False

    # different action
    if (
        isinstance(a, ActionsNode | FunnelExclusionActionsNode)
        and isinstance(b, ActionsNode | FunnelExclusionActionsNode)
        and a.id != b.id
    ):
        return False

    # different event
    if (
        isinstance(a, EventsNode | FunnelExclusionEventsNode)
        and isinstance(b, EventsNode | FunnelExclusionEventsNode)
        and a.event != b.event
    ):
        return False

    # different data source
    if (
        isinstance(a, DataWarehouseNode)
        and isinstance(b, DataWarehouseNode)
        and (a.id != b.id or a.id_field != b.id_field)
    ):
        return False

    # different properties
    if compare_properties and _sorted_property_reprs(a.properties) != _sorted_property_reprs(b.properties):
        return False

    # different fixed properties
    if compare_properties and _sorted_property_reprs(a.fixedProperties) != _sorted_property_reprs(b.fixedProperties):
        return False

    # TODO: compare math (only for trends)

    return True


def is_superset(a: EntityNode, b: EntityNode | ExclusionEntityNode) -> bool:
    """Checks if this entity is a superset version of other. The nodes match and the properties of (a) is a subset of the properties of (b)."""

    if not is_equal(a, b, compare_properties=False):
        return False

    properties_a = Counter(_sorted_property_reprs(a.properties))
    properties_b = Counter(_sorted_property_reprs(b.properties))

    if len(properties_a - properties_b) != 0:
        return False

    fixed_properties_a = Counter(_sorted_property_reprs(a.fixedProperties))
    fixed_properties_b = Counter(_sorted_property_reprs(b.fixedProperties))

    return len(fixed_properties_a - fixed_properties_b) == 0


def _sorted_property_reprs(properties: list[AnyPropertyFilter] | None) -> list[str]:
    return sorted(_semantic_property_repr(prop) for prop in (properties or []) if _semantic_property_repr(prop) != "")


def _semantic_property_repr(property: AnyPropertyFilter) -> str:
    if isinstance(property, EmptyPropertyFilter):
        return ""
    elif isinstance(property, HogQLPropertyFilter) or isinstance(property, CohortPropertyFilter):
        return f"{property.type}: {property.key} {property.value}"
    else:
        return f"{property.type}: {property.key} {property.operator} {property.value}"


def entity_to_expr(entity: EntityNode, team: Team) -> ast.Expr:
    filters: list[ast.Expr] = []

    if isinstance(entity, EventsNode) and entity.event is not None:
        filters.append(
            ast.CompareOperation(
                op=ast.CompareOperationOp.Eq,
                left=ast.Field(chain=["event"]),
                right=ast.Constant(value=entity.event),
            )
        )
    elif isinstance(entity, ActionsNode):
        try:
            action = Action.objects.get(pk=entity.id, team__project_id=team.project_id)
            filters.append(action_to_expr(action))
        except Action.DoesNotExist:
            raise ValueError(f"Action with ID `{entity.id}` does not exist.")
    else:
        raise ValueError(f"`{entity.kind}` nodes are not supported in this context.")

    if entity.properties is not None and entity.properties != []:
        filters.append(property_to_expr(entity.properties, team))

    if entity.fixedProperties is not None and entity.fixedProperties != []:
        filters.append(property_to_expr(entity.fixedProperties, team))

    if len(filters) == 0:
        return ast.Constant(value=True)
    if len(filters) == 1:
        return filters[0]
    else:
        return ast.And(exprs=filters)
