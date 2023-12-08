import dataclasses
import json
from pydantic import BaseModel


def pretty_print_in_tests(query: str, team_id: int) -> str:
    return (
        query.replace("SELECT", "\nSELECT")
        .replace("FROM", "\nFROM")
        .replace("WHERE", "\nWHERE")
        .replace("GROUP", "\nGROUP")
        .replace("HAVING", "\nHAVING")
        .replace("LIMIT", "\nLIMIT")
        .replace("SETTINGS", "\nSETTINGS")
        .replace(f"team_id, {team_id})", "team_id, 420)")
    )


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
