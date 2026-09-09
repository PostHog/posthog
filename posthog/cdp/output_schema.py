"""Validation for a user-supplied JSON Schema that an agent's output is checked against.

Shared by every product that lets a user configure an output schema (signals scouts, workflow AI
tasks), so the same constructs are accepted and the same attacks on the validating worker are
refused everywhere. The schema is user-controlled: a remote `$ref` would make the validator fetch
an arbitrary URL at validation time (SSRF), and a pathological regex pins the worker and cannot
be interrupted. Both fail closed here, at write time.
"""

from __future__ import annotations

import json
from typing import Any

from jsonschema import Draft202012Validator

# Serialized size cap on the configured schema, so it stays a cheap per-payload validation, not
# a document.
MAX_SCHEMA_BYTES = 20_000

# Keys whose value is a reference the validator would try to resolve.
_REFERENCE_KEYS = ("$ref", "$dynamicRef", "$recursiveRef")
# Regex-bearing keywords. Python's `re` backtracks, so a pathological pattern (`^(a+)+$`)
# against a near-matching payload can pin a worker for minutes, and nothing can interrupt a
# match in flight — the size caps bound bytes, not regex time. Enums, types, ranges and
# required cover what an output schema needs, so these fail closed.
_REGEX_KEYWORDS = ("pattern", "patternProperties")
# Keys whose immediate child keys are user-chosen names (e.g. property names), not JSON
# Schema keywords — a property legitimately named `pattern` must not read as the keyword.
_NAME_MAP_KEYS = ("properties", "$defs", "definitions", "dependentSchemas")
# Keys whose value is data, not schema — an example payload may contain a `pattern` key.
_DATA_KEYS = ("default", "const", "enum", "examples")


class OutputSchemaError(ValueError):
    """The supplied JSON Schema itself is invalid (raised at config-write time)."""


def validate_output_schema(schema: Any, *, field_name: str = "output_schema") -> dict[str, Any]:
    """Validate a user-supplied JSON Schema and return it.

    Requires a JSON object rooted at `"type": "object"` — the output is stored as a dict, and an
    object root is what keeps each field addressable downstream — and bounds serialized size.
    `field_name` only shapes the error message so each caller names its own field.
    """
    if not isinstance(schema, dict) or not schema:
        raise OutputSchemaError(f"{field_name} must be a non-empty JSON object")
    if schema.get("type") != "object":
        raise OutputSchemaError(f'{field_name} must declare "type": "object" at its root')
    encoded = json.dumps(schema)
    if len(encoded.encode("utf-8")) > MAX_SCHEMA_BYTES:
        raise OutputSchemaError(f"{field_name} exceeds {MAX_SCHEMA_BYTES} bytes serialized")
    _assert_supported_constructs(schema, field_name)
    try:
        Draft202012Validator.check_schema(schema)
    except Exception as exc:
        raise OutputSchemaError(f"{field_name} is not a valid JSON Schema: {exc}") from exc
    return schema


def _assert_supported_constructs(node: Any, field_name: str) -> None:
    """Reject schema constructs that would let a schema author attack the validating worker.

    Two families, both walked recursively. Non-fragment `$ref` / `$dynamicRef` /
    `$recursiveRef` would ask the validator to fetch an arbitrary URL at validation time
    (SSRF) — only in-document `#...` references are supported. Regex keywords (`pattern`,
    `patternProperties`) are rejected outright (see `_REGEX_KEYWORDS`). Name-map containers
    (`properties`, `$defs`, ...) and data positions (`default`, `enum`, ...) are walked without
    reading their user-chosen keys as keywords."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key in _DATA_KEYS:
                continue
            if key in _NAME_MAP_KEYS and isinstance(value, dict):
                for subschema in value.values():
                    _assert_supported_constructs(subschema, field_name)
                continue
            if key in _REFERENCE_KEYS and isinstance(value, str) and not value.startswith("#"):
                raise OutputSchemaError(
                    f"{field_name} must not use remote references ({key}: {value!r}); "
                    "only in-document '#/...' references are supported"
                )
            if key in _REGEX_KEYWORDS:
                raise OutputSchemaError(
                    f"{field_name} must not use regex keywords ({key}): a pathological "
                    "pattern can stall validation indefinitely. Express the constraint with enum, "
                    "type, length, or numeric bounds instead."
                )
            _assert_supported_constructs(value, field_name)
    elif isinstance(node, list):
        for item in node:
            _assert_supported_constructs(item, field_name)
