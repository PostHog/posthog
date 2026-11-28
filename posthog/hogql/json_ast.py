"""
JSON AST serializer and deserializer

Converts JSON strings returned by the C++ HogQL parser back into Python AST objects.

Performance: enum-typed fields and dict-shaped fields are precomputed per class
at import time. The hot loop uses orjson for JSON parsing and avoids
`get_type_hints` / `hasattr` per node.
"""

import math
import inspect
import dataclasses
from datetime import date, datetime
from enum import Enum
from typing import Any, get_type_hints
from uuid import UUID

import orjson

from posthog.hogql import ast
from posthog.hogql.constants import HogQLQuerySettings
from posthog.hogql.errors import (
    ExposedHogQLError,
    SyntaxError as HogQLSyntaxError,
)

NODE_MAP: dict[str, type[ast.AST]] = {
    cls.__name__: cls
    for _, cls in inspect.getmembers(ast, inspect.isclass)
    if issubclass(cls, ast.AST) and cls is not ast.AST
}

# Fields whose JSON values are dicts of {key: child_node} rather than child
# nodes themselves. The C++ parser emits these for `window_exprs`, `ctes`
# (when not list-encoded), and `replace`.
_DICT_FIELDS = frozenset({"window_exprs", "ctes", "replace"})

# Per-node fields whose inner JSON arrays should land as Python `tuple` (not
# `list`). JSON has no tuple type, so cpp / rust-json emit `[[k,v]]` for fields
# the Python AST types as `list[tuple[...]]`. Without this map the deserialiser
# would return `list[list]`, which doesn't `==` the `list[tuple]` that
# `rust-py` and `CloningVisitor` build — surfacing as bogus "position-only"
# shadow mismatches on every Hog program containing a dict literal or a
# try/catch.
_TUPLE_INNER_FIELDS: dict[str, frozenset[str]] = {
    "Dict": frozenset({"items"}),
    "TryCatchStatement": frozenset({"catches"}),
}

# Per-class enum-typed field map, built once at import. Saves a per-node
# `get_type_hints(cls)` call and a `hasattr(t, "__members__")` check.
_ENUM_FIELDS: dict[type, dict[str, Any]] = {}


def _build_enum_fields() -> None:
    for cls in NODE_MAP.values():
        try:
            hints = get_type_hints(cls)
        except Exception:
            continue
        enum_map = {key: t for key, t in hints.items() if hasattr(t, "__members__")}
        if enum_map:
            _ENUM_FIELDS[cls] = enum_map


_build_enum_fields()

# Cheap canary: a future AST class whose `get_type_hints` fails at import would
# be silently skipped above. Assert the known enum-bearing classes registered
# so a regression to "no enum coercion" trips here rather than being noticed
# only by a confused downstream consumer.
assert ast.ArithmeticOperation in _ENUM_FIELDS, "_build_enum_fields did not register ArithmeticOperation"
assert ast.CompareOperation in _ENUM_FIELDS, "_build_enum_fields did not register CompareOperation"


_SPECIAL_FLOATS = {"Infinity": float("inf"), "-Infinity": float("-inf"), "NaN": float("nan")}


_INT64_MIN, _INT64_MAX = -(2**63), 2**63 - 1


def _parse_large_int_literal(value: str) -> int | None:
    """Parse an integer literal the parser kept lossless as a string — a
    decimal or `0x`-prefixed hex magnitude with an optional leading `-`.
    An integer wider than 64 bits can't round-trip as a native JSON
    number, so the parser emits the exact digits in the same
    `value_type: "number"` string envelope the non-finite floats use.
    Returns None when `value` isn't an integer literal."""
    body = value[1:] if value.startswith("-") else value
    base = 16 if body[:2] in ("0x", "0X") else 10
    try:
        return int(value, base)
    except ValueError:
        return None


def deserialize_ast(json_str: str) -> ast.AST:
    """Deserialize a JSON string into a Python AST object."""
    return _deserialize_node(orjson.loads(json_str))


def _deserialize_node(data: Any) -> Any:
    if data is None:
        return None
    if isinstance(data, list):
        return [_deserialize_node(item) for item in data]
    if not isinstance(data, dict):
        return data

    if data.get("error") is True:
        error_type = data.get("type", "Error")
        message = data.get("message", "Unknown error")
        start = data.get("start") or {}
        end = data.get("end") or {}
        # A parser that tags an error `SyntaxError` means a malformed
        # query — surface it as `SyntaxError` (a subclass of
        # `ExposedHogQLError`) so callers can distinguish it, matching
        # what the C++ parser raises natively.
        if error_type == "SyntaxError":
            raise HogQLSyntaxError(message, start=start.get("offset"), end=end.get("offset"))
        raise ExposedHogQLError(message, start=start.get("offset"), end=end.get("offset"))

    node_type = data.get("node")
    if node_type is None:
        raise ValueError(f"Invalid AST node: missing 'node' field in {data}")
    ast_class = NODE_MAP.get(node_type)
    if ast_class is None:
        raise ValueError(f"Unknown AST node type: {node_type}")

    enum_map = _ENUM_FIELDS.get(ast_class)
    is_constant = node_type == "Constant"
    value_type = data.get("value_type") if is_constant else None

    kwargs: dict[str, Any] = {}
    for key, value in data.items():
        if key == "node" or key == "value_type":
            continue

        # start/end are encoded as `{"offset": N}` envelopes.
        if (key == "start" or key == "end") and isinstance(value, dict):
            offset = value.get("offset")
            if offset is not None:
                kwargs[key] = offset
                continue

        if is_constant and key == "value":
            kwargs[key] = _deserialize_constant_value(value, value_type)
            continue

        if key == "settings" and isinstance(value, dict):
            kwargs[key] = HogQLQuerySettings(**value)
            continue

        # `ctes` may be a list of nodes carrying a `name` (preserves order)
        # — fold it into a dict keyed by the name.
        if key == "ctes" and isinstance(value, list):
            kwargs[key] = {item["name"]: _deserialize_node(item) for item in value}
            continue

        # Inner-array → tuple for fields the Python AST types as `list[tuple]`
        # (see `_TUPLE_INNER_FIELDS`). JSON arrays default to `list` everywhere
        # else; this targeted conversion keeps `==` parity with `rust-py` /
        # `CloningVisitor`, which both build tuples.
        node_tuple_fields = _TUPLE_INNER_FIELDS.get(node_type)
        if node_tuple_fields is not None and key in node_tuple_fields and isinstance(value, list):
            kwargs[key] = [
                tuple(_deserialize_node(item) for item in row) if isinstance(row, list) else _deserialize_node(row)
                for row in value
            ]
            continue

        # Other dict-shaped fields: {key: child_node}.
        if key in _DICT_FIELDS and isinstance(value, dict) and not isinstance(value.get("node"), str):
            kwargs[key] = {k: _deserialize_node(v) for k, v in value.items()}
            continue

        deserialized = _deserialize_node(value)

        # Coerce enum strings to their StrEnum members.
        if enum_map is not None and isinstance(deserialized, str):
            enum_type = enum_map.get(key)
            if enum_type is not None:
                try:
                    deserialized = enum_type[deserialized]
                except KeyError:
                    pass

        kwargs[key] = deserialized

    return ast_class(**kwargs)


def _deserialize_constant_value(value: Any, value_type: str | None) -> Any:
    if value_type is None:
        if isinstance(value, list):
            return [_deserialize_constant_item(item) for item in value]
        return value
    if value_type == "number":
        return _deserialize_number(value)
    if value_type == "datetime":
        return datetime.fromisoformat(value)
    if value_type == "date":
        return date.fromisoformat(value)
    if value_type == "uuid":
        return UUID(value)
    if value_type == "tuple":
        return tuple(_deserialize_constant_item(item) for item in value)
    raise ValueError(f"Unknown constant value_type: {value_type!r}")


def _deserialize_number(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    # Numeric Constants emitted as strings: non-finite floats
    # (Infinity / NaN) and integer literals too wide to round-trip
    # as a native JSON number.
    special = _SPECIAL_FLOATS.get(value)
    if special is not None:
        return special
    int_value = _parse_large_int_literal(value)
    if int_value is not None:
        return int_value
    raise ValueError(f"Unknown numeric constant value: {value!r}")


def _deserialize_constant_item(item: Any) -> Any:
    if isinstance(item, dict):
        return _deserialize_constant_value(item["value"], item["value_type"])
    return _deserialize_constant_value(item, None)


def serialize_ast(node: ast.AST) -> str:
    return orjson.dumps(
        node, default=_serialize_object, option=orjson.OPT_PASSTHROUGH_DATACLASS | orjson.OPT_PASSTHROUGH_DATETIME
    ).decode()


def _serialize_object(value: Any) -> Any:
    if isinstance(value, ast.AST):
        return _serialize_node(value)
    if type(value) is HogQLQuerySettings:
        return value.model_dump(exclude_none=True)
    raise TypeError(f"Cannot serialize a value of type {type(value).__name__}")


_SERIALIZED_FIELDS: dict[type[ast.AST], tuple[tuple[str, bool], ...]] = {
    node_class: tuple(
        (field.name, field.default is None) for field in dataclasses.fields(node_class) if field.name != "type"
    )
    for node_class in NODE_MAP.values()
}


def _serialize_node(node: ast.AST) -> dict[str, Any]:
    node_class = type(node)
    enum_fields = _ENUM_FIELDS.get(node_class, {})
    data: dict[str, Any] = {"node": node_class.__name__}
    for name, defaults_to_none in _SERIALIZED_FIELDS[node_class]:
        value = getattr(node, name)
        if value is None:
            if not defaults_to_none:
                data[name] = None
        elif name == "start" or name == "end":
            data[name] = {"offset": value}
        elif name == "value" and node_class is ast.Constant:
            data[name], value_type = _serialize_constant_value(value)
            if value_type is not None:
                data["value_type"] = value_type
        elif name in enum_fields and isinstance(value, Enum):
            data[name] = value.name
        else:
            data[name] = value
    return data


def _serialize_constant_value(value: Any) -> tuple[Any, str | None]:
    if value is None or isinstance(value, str | bool):
        return value, None
    if isinstance(value, int | float):
        return _serialize_number(value)
    if isinstance(value, datetime):
        return value.isoformat(), "datetime"
    if isinstance(value, date):
        return value.isoformat(), "date"
    if isinstance(value, UUID):
        return str(value), "uuid"
    if isinstance(value, list):
        return [_serialize_constant_item(item) for item in value], None
    if isinstance(value, tuple):
        return [_serialize_constant_item(item) for item in value], "tuple"
    raise TypeError(f"Cannot serialize a constant of type {type(value).__name__}")


def _serialize_number(value: int | float) -> tuple[Any, str | None]:
    if isinstance(value, int):
        if _INT64_MIN <= value <= _INT64_MAX:
            return value, None
        return str(value), "number"
    if math.isfinite(value):
        return value, None
    if math.isnan(value):
        return "NaN", "number"
    return ("Infinity" if value > 0 else "-Infinity"), "number"


def _serialize_constant_item(item: Any) -> Any:
    value, value_type = _serialize_constant_value(item)
    if value_type is None:
        return value
    return {"value": value, "value_type": value_type}
