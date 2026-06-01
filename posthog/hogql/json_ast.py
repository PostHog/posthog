"""
JSON AST Deserializer

Converts JSON strings returned by the C++ HogQL parser back into Python AST objects.

Performance: enum-typed fields and dict-shaped fields are precomputed per class
at import time. The hot loop uses orjson for JSON parsing and avoids
`get_type_hints` / `hasattr` per node.
"""

import inspect
from typing import Any, get_type_hints

import orjson

from posthog.hogql import ast
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

        # Numeric Constants emitted as strings: non-finite floats
        # (Infinity / NaN) and integer literals too wide to round-trip
        # as a native JSON number.
        if is_constant and key == "value" and value_type == "number" and isinstance(value, str):
            special = _SPECIAL_FLOATS.get(value)
            if special is not None:
                kwargs[key] = special
                continue
            int_value = _parse_large_int_literal(value)
            if int_value is not None:
                kwargs[key] = int_value
                continue
            raise ValueError(f"Unknown numeric constant value: {value!r}")

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
        if key in _DICT_FIELDS and isinstance(value, dict) and "node" not in value:
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
