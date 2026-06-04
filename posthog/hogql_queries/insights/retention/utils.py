from typing import cast

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr

from posthog.clickhouse.query_tagging import tag_contains_user_hogql
from posthog.hogql_queries.insights.utils.breakdowns import strip_user_aliases


def breakdown_extract_expr(property_name: str, breakdown_type: str, group_type_index: int | None = None) -> ast.Expr:
    if breakdown_type == "cohort":
        # For cohort breakdowns, filtering is handled in the WHERE clause
        # so we just return the cohort ID as a constant
        return ast.Constant(value=str(property_name))

    if breakdown_type == "hogql":
        # The value is a raw HogQL expression, not a property name. Parse it and
        # strip any display-only `AS` aliases the user added, which would otherwise
        # break the surrounding toString()/argMinIf() wrapping.
        tag_contains_user_hogql()
        property_field: ast.Expr = strip_user_aliases(parse_expr(property_name))
    else:
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

        property_field = ast.Field(chain=cast(list[str | int], properties_chain))

    # Convert the property to String first, then handle NULLs.
    # This avoids potential type mismatches (e.g., mixing Float64 and String for NULLs).
    to_string_expr = ast.Call(name="toString", args=[property_field])
    # Replace NULL with empty string ''
    return ast.Call(name="ifNull", args=[to_string_expr, ast.Constant(value="")])
