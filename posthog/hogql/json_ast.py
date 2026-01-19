"""
JSON AST Deserializer

Converts JSON strings returned by the C++ HogQL parser back into Python AST objects.
"""

import json
import inspect
from typing import Any, get_type_hints

from posthog.hogql import ast
from posthog.hogql.errors import (
    ExposedHogQLError,
    SyntaxError as HogQLSyntaxError,
)


def deserialize_ast(json_str: str) -> ast.AST:
    """Deserialize a JSON string into a Python AST object."""
    data = json.loads(json_str)
    return _deserialize_node(data)


NODE_MAP = {
    cls.__name__: cls
    for _, cls in inspect.getmembers(ast, inspect.isclass)
    if issubclass(cls, ast.AST) and cls is not ast.AST
}


def _convert_special_float(value: str) -> float:
    """Convert string representation of special float values to actual floats."""
    if value == "Infinity":
        return float("inf")
    elif value == "-Infinity":
        return float("-inf")
    elif value == "NaN":
        return float("nan")
    raise ValueError(f"Unknown special float value: {value}")


def _deserialize_node(data: Any) -> Any:
    """Recursively deserialize a JSON node into an AST object."""
    if data is None:
        return None

    if isinstance(data, list):
        return [_deserialize_node(item) for item in data]

    if not isinstance(data, dict):
        return data

    if "error" in data and data["error"] is True:
        error_type = data.get("type", "Error")
        message = data.get("message", "Unknown error")
        start = data.get("start", {})
        end = data.get("end", {})

        if error_type == "SyntaxError" and "reserved keyword" in message:
            raise HogQLSyntaxError(message, start=start.get("offset"), end=end.get("offset"))
        else:
            raise ExposedHogQLError(message, start=start.get("offset"), end=end.get("offset"))

    if "node" not in data:
        raise ValueError(f"Invalid AST node: missing 'node' field in {data}")

    node_type = data["node"]

    ast_class = NODE_MAP.get(node_type)
    if ast_class is None:
        raise ValueError(f"Unknown AST node type: {node_type}")

    try:
        type_hints = get_type_hints(ast_class)
    except Exception:
        type_hints = {}

    kwargs = {}
    for key, value in data.items():
        if key in ("node", "value_type"):
            continue

        if key in ("start", "end") and isinstance(value, dict) and "offset" in value:
            kwargs[key] = value["offset"]
            continue

        # Handle special float values for Constant nodes
        if node_type == "Constant" and key == "value" and data.get("value_type") == "number":
            if isinstance(value, str) and value in ("Infinity", "-Infinity", "NaN"):
                kwargs[key] = _convert_special_float(value)
                continue

        if isinstance(value, dict) and "node" not in value and key in ("window_exprs", "ctes"):
            deserialized_value: Any = {k: _deserialize_node(v) for k, v in value.items()}
        else:
            deserialized_value = _deserialize_node(value)

            if key in type_hints:
                field_type = type_hints[key]
                if hasattr(field_type, "__members__") and isinstance(deserialized_value, str):
                    try:
                        deserialized_value = field_type[deserialized_value]
                    except KeyError:
                        pass

        kwargs[key] = deserialized_value

    return ast_class(**kwargs)
