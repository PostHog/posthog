from collections.abc import Iterable
from typing import Optional
from xml.etree import ElementTree as ET

import yaml

from posthog.taxonomy.taxonomy import CORE_FILTER_DEFINITIONS_BY_GROUP


def format_property_values(sample_values: list, sample_count: Optional[int] = 0, format_as_string: bool = False) -> str:
    if len(sample_values) == 0 or sample_count == 0:
        return f"The property does not have any values in the taxonomy."

    # Add quotes to the String type, so the LLM can easily infer a type.
    # Strings like "true" or "10" are interpreted as booleans or numbers without quotes, so the schema generation fails.
    # Remove the floating point the value is an integer.
    formatted_sample_values: list[str] = []
    for value in sample_values:
        if format_as_string:
            formatted_sample_values.append(f'"{value}"')
        elif isinstance(value, float) and value.is_integer():
            formatted_sample_values.append(str(int(value)))
        else:
            formatted_sample_values.append(str(value))
    prop_values = ", ".join(formatted_sample_values)

    # If there wasn't an exact match with the user's search, we provide a hint that LLM can use an arbitrary value.
    if sample_count is None:
        return f"{prop_values} and many more distinct values."
    elif sample_count > len(sample_values):
        diff = sample_count - len(sample_values)
        return f"{prop_values} and {diff} more distinct value{'' if diff == 1 else 's'}."

    return prop_values


def format_properties_xml(children: list[tuple[str, str | None, str | None]]):
    root = ET.Element("properties")
    property_type_to_tag = {}

    for name, property_type, description in children:
        # Do not include properties that are ambiguous.
        if property_type is None:
            continue
        if property_type not in property_type_to_tag:
            property_type_to_tag[property_type] = ET.SubElement(root, property_type)

        type_tag = property_type_to_tag[property_type]
        prop = ET.SubElement(type_tag, "prop")
        ET.SubElement(prop, "name").text = name
        if description:
            ET.SubElement(prop, "description").text = description

    return ET.tostring(root, encoding="unicode")


def format_properties_yaml(children: list[tuple[str, str | None, str | None]]):
    properties_by_type: dict = {}

    for name, property_type, description in children:
        # Do not include properties that are ambiguous.
        if property_type is None:
            continue

        if property_type not in properties_by_type:
            properties_by_type[property_type] = []

        prop_dict = {"name": name}
        if description:
            prop_dict["description"] = description

        properties_by_type[property_type].append(prop_dict)

    result = {"properties": properties_by_type}
    return yaml.dump(result, default_flow_style=False, sort_keys=False)


def enrich_props_with_descriptions(entity: str, props: Iterable[tuple[str, str | None]]):
    enriched_props = []
    mapping = {
        "session": CORE_FILTER_DEFINITIONS_BY_GROUP["session_properties"],
        "person": CORE_FILTER_DEFINITIONS_BY_GROUP["person_properties"],
        "event": CORE_FILTER_DEFINITIONS_BY_GROUP["event_properties"],
    }
    for prop_name, prop_type in props:
        description = None
        if entity_definition := mapping.get(entity, {}).get(prop_name):
            if entity_definition.get("system") or entity_definition.get("ignored_in_assistant"):
                continue
            description = entity_definition.get("description_llm") or entity_definition.get("description")
        enriched_props.append((prop_name, prop_type, description))
    return enriched_props
