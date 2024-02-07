from posthog.schema import (
    ActionsNode,
    CohortPropertyFilter,
    EmptyPropertyFilter,
    EventsNode,
    HogQLPropertyFilter,
)
from posthog.types import AnyPropertyFilter, EntityNode
from collections import Counter


def is_equal(a: EntityNode, b: EntityNode, compare_properties=True) -> bool:
    """Checks if two entities are semantically equal."""

    # different type
    if type(a) != type(b):
        return False

    # different action
    if isinstance(a, ActionsNode) and isinstance(b, ActionsNode) and a.id != b.id:
        return False

    # different event
    if isinstance(a, EventsNode) and isinstance(b, EventsNode) and a.event != b.event:
        return False

    # different properties
    if compare_properties and _sorted_property_reprs(a.properties) != _sorted_property_reprs(b.properties):
        return False

    # different fixed properties
    if compare_properties and _sorted_property_reprs(a.fixedProperties) != _sorted_property_reprs(b.fixedProperties):
        return False

    # TODO: compare math (only for trends)

    return True


def is_superset(a: EntityNode, b: EntityNode) -> bool:
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
