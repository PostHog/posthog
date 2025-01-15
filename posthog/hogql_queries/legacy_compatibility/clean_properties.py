from posthog.schema import PropertyOperator


def clean_global_properties(properties: dict | list[dict] | None):
    if properties is None or len(properties) == 0:
        # empty properties
        return None
    elif is_old_style_properties(properties):
        # old style properties
        properties = transform_old_style_properties(properties)
        properties = {
            "type": "AND",
            "values": [{"type": "AND", "values": properties}],
        }
        return clean_property_group_filter(properties)
    elif isinstance(properties, list):
        # list of property filters
        properties = {
            "type": "AND",
            "values": [{"type": "AND", "values": properties}],
        }
        return clean_property_group_filter(properties)
    elif (
        isinstance(properties, dict)
        and properties.get("type") in ["AND", "OR"]
        and not any(property.get("type") in ["AND", "OR"] for property in properties["values"])
    ):
        # property group filter value
        properties = {
            "type": "AND",
            "values": [properties],
        }
        return clean_property_group_filter(properties)
    else:
        # property group filter
        return clean_property_group_filter(properties)


def clean_entity_properties(properties: list[dict] | dict | None):
    if properties is None or len(properties) == 0:
        # empty properties
        return None
    elif is_old_style_properties(properties):
        # old style properties
        return transform_old_style_properties(properties)
    elif isinstance(properties, list):
        # list of property filters
        return list(map(clean_property, properties))
    elif (
        isinstance(properties, dict)
        and properties.get("type") in ["AND", "OR"]
        and not any(property.get("type") in ["AND", "OR"] for property in properties["values"])
    ):
        # property group filter value
        return list(map(clean_property, properties["values"]))
    else:
        raise ValueError("Unexpected format of entity properties.")


def clean_property_group_filter(properties: dict):
    properties["values"] = clean_property_group_filter_values(properties["values"])
    return properties


def clean_property_group_filter_values(properties: list[dict]):
    cleaned = [clean_property_group_filter_value(property) for property in properties if property]
    return cleaned


def clean_property_group_filter_value(property: dict):
    if property.get("type") in ["AND", "OR"]:
        # property group filter value
        property["values"] = clean_property_group_filter_values(property["values"])
        return property
    else:
        # property filter
        return clean_property(property)


def clean_property(property: dict):
    cleaned_property = {**property}

    # fix type typo
    if cleaned_property.get("type") == "events":
        cleaned_property["type"] = "event"

    # fix value key typo
    if cleaned_property.get("values") is not None and cleaned_property.get("value") is None:
        cleaned_property["value"] = cleaned_property.pop("values")

    # convert precalculated and static cohorts to cohorts
    if cleaned_property.get("type") in ("precalculated-cohort", "static-cohort"):
        cleaned_property["type"] = "cohort"

    # fix invalid property key for cohorts
    if cleaned_property.get("type") == "cohort":
        if cleaned_property.get("key") != "id":
            cleaned_property["key"] = "id"
        if cleaned_property.get("operator") is None:
            cleaned_property["operator"] = (
                PropertyOperator.NOT_IN.value if cleaned_property.get("negation", False) else PropertyOperator.IN_.value
            )
        if "negation" in cleaned_property:
            del cleaned_property["negation"]

    # set a default operator for properties that support it, but don't have an operator set
    if is_property_with_operator(cleaned_property) and cleaned_property.get("operator") is None:
        cleaned_property["operator"] = "exact"

    # remove the operator for properties that don't support it, but have it set
    if not is_property_with_operator(cleaned_property) and cleaned_property.get("operator") is not None:
        del cleaned_property["operator"]

    # remove none from values
    if isinstance(cleaned_property.get("value"), list):
        cleaned_property["value"] = list(filter(lambda x: x is not None, cleaned_property.get("value")))  # type: ignore

    # remove keys without concrete value
    cleaned_property = {key: value for key, value in cleaned_property.items() if value is not None}

    return cleaned_property


def is_property_with_operator(property: dict):
    return property.get("type") not in ("hogql",)


# old style dict properties e.g. {"utm_medium__icontains": "email"}
def is_old_style_properties(properties):
    return isinstance(properties, dict) and len(properties) == 1 and properties.get("type") not in ("AND", "OR")


def transform_old_style_properties(properties):
    key = next(iter(properties.keys()))
    value = next(iter(properties.values()))
    key_split = key.split("__")
    return [
        {
            "key": key_split[0],
            "value": value,
            "operator": key_split[1] if len(key_split) > 1 else "exact",
            "type": "event",
        }
    ]
