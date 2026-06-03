from collections.abc import Callable, Iterable

from posthog.taxonomy.taxonomy import CORE_FILTER_DEFINITIONS_BY_GROUP, CoreFilterDefinition

from products.event_definitions.backend.models.property_definition import PropertyDefinition, PropertyType

type EventPropertyDefinition = PropertyDefinition | CoreFilterDefinition
type FormatPropertyValues = Callable[[str, list[str | int | float], int | None, bool], str]


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
    return property_type in (PropertyType.String, PropertyType.Datetime)


def get_virtual_event_property_sample_values(
    property_definition: CoreFilterDefinition,
) -> tuple[list[str | int | float], int | None]:
    examples = property_definition.get("examples")
    if examples:
        return examples, None
    if property_definition.get("type") == "Boolean":
        return ["true", "false"], 2
    return [], None


def format_virtual_event_property_values(
    property_name: str,
    property_definition: CoreFilterDefinition,
    format_property_values: FormatPropertyValues,
) -> str:
    sample_values, sample_count = get_virtual_event_property_sample_values(property_definition)
    if sample_values:
        return format_property_values(
            property_name,
            sample_values,
            sample_count,
            event_property_is_string_like(property_definition),
        )

    return (
        f"The property {property_name} is a virtual event property computed at query time, "
        "so the taxonomy may not have stored sample values."
    )
