import re
import json
import dataclasses
from typing import Any

from posthog.test.base import clean_varying_query_parts

from pydantic import BaseModel

from posthog.schema import HogQLQueryModifiers

from posthog.hogql.query import execute_hogql_query


def execute_hogql_query_with_timings(*args, **kwargs):
    modifiers = kwargs.get("modifiers") or HogQLQueryModifiers()
    modifiers.timings = True
    kwargs["modifiers"] = modifiers
    return execute_hogql_query(*args, **kwargs)


def pretty_print_in_tests(query: str | None, team_id: int) -> str:
    if query is None:
        return ""
    query = (
        query.replace("SELECT", "\nSELECT")
        .replace("FROM", "\nFROM")
        .replace("WHERE", "\nWHERE")
        .replace("GROUP", "\nGROUP")
        .replace("HAVING", "\nHAVING")
        .replace("LIMIT", "\nLIMIT")
        .replace("SETTINGS", "\nSETTINGS")
        .replace(f"team_id, {team_id})", "team_id, 420)")
    )
    query = re.sub(r"in_cohort__[0-9]+", "in_cohort__XX", query)
    query = re.sub(r"cohort_id, [0-9]+", "cohort_id, XX", query)
    query = re.sub(r"RANDOM_TEST_ID::[a-f0-9\-]+", "RANDOM_TEST_ID::UUID", query)
    return query


def pretty_print_response_in_tests(response: Any, team_id: int) -> str:
    clickhouse = response.clickhouse
    hogql = response.hogql
    query = "-- ClickHouse\n" + clickhouse + "\n\n-- HogQL\n" + hogql
    return clean_varying_query_parts(pretty_print_in_tests(query, team_id), False)


def pretty_dataclasses(obj, seen=None, indent=0):
    if seen is None:
        seen = set()

    indent_space = " " * indent
    next_indent = " " * (indent + 2)

    if isinstance(obj, BaseModel):
        obj = obj.model_dump()

    if dataclasses.is_dataclass(obj):
        obj_id = id(obj)
        if obj_id in seen:
            return "<recursion ...>"
        seen.add(obj_id)

        field_strings = []
        fields = sorted(dataclasses.fields(obj), key=lambda f: f.name)
        for f in fields:
            value = getattr(obj, f.name)
            if value is not None:
                formatted_value = pretty_dataclasses(value, seen, indent + 2)
                field_strings.append(f"{next_indent}{f.name}: {formatted_value}")

        return "{\n" + "\n".join(field_strings) + "\n" + indent_space + "}"

    elif isinstance(obj, list):
        if len(obj) == 0:
            return "[]"
        elements = [pretty_dataclasses(item, seen, indent + 2) for item in obj]
        return "[\n" + ",\n".join(next_indent + element for element in elements) + "\n" + indent_space + "]"

    elif isinstance(obj, dict):
        if len(obj) == 0:
            return "{}"
        sorted_items = sorted(obj.items())
        key_value_pairs = [f"{k}: {pretty_dataclasses(v, seen, indent + 2)}" for k, v in sorted_items]
        return "{\n" + ",\n".join(next_indent + pair for pair in key_value_pairs) + "\n" + indent_space + "}"

    elif isinstance(obj, str):
        return json.dumps(obj)

    elif callable(obj):
        return "<function>"

    else:
        return str(obj)
