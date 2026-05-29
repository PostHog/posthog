from collections.abc import Iterable
from typing import TypeAlias

from posthog.taxonomy.taxonomy import CORE_FILTER_DEFINITIONS_BY_GROUP, CoreFilterDefinition

from products.event_definitions.backend.models.property_definition import PropertyDefinition, PropertyType

EventPropertyDefinition: TypeAlias = PropertyDefinition | CoreFilterDefinition


def get_virtual_event_property_definition(property_name: str) -> CoreFilterDefinition | None:
    definition = CORE_FILTER_DEFINITIONS_BY_GROUP["event_properties"].get(property_name)
    if definition is None or definition.get("virtual") is not True:
        return None
    return definition


def merge_virtual_event_property_definitions(
    property_definitions: dict[str, PropertyDefinition], property_names: Iterable[str]
) -> dict[str, EventPropertyDefinition]:
    merged: dict[str, EventPropertyDefinition] = dict(property_definitions)
    for property_name in property_names:
        if property_name in merged:
            continue
        if virtual_definition := get_virtual_event_property_definition(property_name):
            merged[property_name] = virtual_definition
    return merged


def get_event_property_definition_type(property_definition: EventPropertyDefinition) -> str | None:
    if isinstance(property_definition, PropertyDefinition):
        return property_definition.property_type
    return property_definition.get("type")


def event_property_is_string_like(property_definition: EventPropertyDefinition) -> bool:
    property_type = get_event_property_definition_type(property_definition)
    return property_type in (PropertyType.String, PropertyType.Datetime, "String", "DateTime")


def get_virtual_event_property_sample_values(
    property_definition: CoreFilterDefinition,
) -> tuple[list[str | int | float], int | None]:
    examples = property_definition.get("examples")
    if examples:
        return examples, None
    if property_definition.get("type") == "Boolean":
        return ["true", "false"], 2
    return [], None
