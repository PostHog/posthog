from typing import cast

from posthog.hogql import ast


def has_cohort_property(properties: object) -> bool:
    """Recursively check if properties contain cohort filters."""
    if isinstance(properties, list):
        for prop in properties:
            if has_cohort_property(prop):
                return True
    elif isinstance(properties, dict):
        if properties.get("type") == "cohort":
            return True
        # Check nested property groups
        if "values" in properties:
            return has_cohort_property(properties["values"])
    elif getattr(properties, "type", None) == "cohort":
        return True
    else:
        property_values = getattr(properties, "values", None)
        if property_values is not None:
            return has_cohort_property(property_values)

    return False


def breakdown_extract_expr(property_name: str, breakdown_type: str, group_type_index: int | None = None) -> ast.Expr:
    if breakdown_type == "cohort":
        # For cohort breakdowns, filtering is handled in the WHERE clause
        # so we just return the cohort ID as a constant
        return ast.Constant(value=str(property_name))

    if breakdown_type == "person":
        if property_name.startswith("$virt_"):
            # Virtual properties exist as expression fields on the persons table
            properties_chain = ["person", property_name]
        else:
            properties_chain = ["person", "properties", property_name]
    elif breakdown_type == "data_warehouse_person_property":
        properties_chain = ["person", *property_name.split(".")]
    elif breakdown_type == "group":
        if property_name.startswith("$virt_"):
            # Virtual properties exist as expression fields on the groups table
            properties_chain = [f"groups_{group_type_index}", property_name]
        else:
            properties_chain = [f"groups_{group_type_index}", "properties", property_name]
    else:
        # Default to event properties
        properties_chain = ["events", "properties", property_name]

    # Convert the property to String first, then handle NULLs.
    # This avoids potential type mismatches (e.g., mixing Float64 and String for NULLs).
    property_field = ast.Field(chain=cast(list[str | int], properties_chain))
    to_string_expr = ast.Call(name="toString", args=[property_field])
    # Replace NULL with empty string ''
    return ast.Call(name="ifNull", args=[to_string_expr, ast.Constant(value="")])
