import json
from typing import Any

from django.conf import settings
from django.core.exceptions import ValidationError

from jsonschema import Draft202012Validator

# Use one cap for every stored collection. Request validation and the locked
# record update both enforce it because separate edits can grow the same value.
MAX_COLLECTION_ITEMS = 2000

STATE_KEY_SCHEMA = {
    "type": "string",
    "minLength": 1,
    "maxLength": 128,
    "not": {"type": "string", "enum": ["__proto__", "constructor", "prototype"]},
}
FIELD_ID_SCHEMA = {"type": "string", "maxLength": 64}
FIELD_KIND_SCHEMA = {"type": "string", "enum": ["text", "list"]}
FIELD_ENTRY_PROPERTIES = {"k": {"type": "string", "minLength": 1, "maxLength": 64}, "v": {}}
STATE_VALUE_SCHEMA = {
    "if": {"type": "object", "required": ["__field"]},
    "then": {
        "type": "object",
        "required": ["__field", "entries", "removed"],
        "properties": {
            "__field": FIELD_KIND_SCHEMA,
            "entries": {
                "type": "object",
                "maxProperties": MAX_COLLECTION_ITEMS,
                "propertyNames": FIELD_ID_SCHEMA,
                "additionalProperties": {
                    "type": "object",
                    "required": ["k", "v"],
                    "properties": FIELD_ENTRY_PROPERTIES,
                },
            },
            "removed": {"type": "array", "maxItems": MAX_COLLECTION_ITEMS, "items": FIELD_ID_SCHEMA},
        },
    },
}
FRAGMENT_PROPERTIES = {
    "id": {"type": "string", "minLength": 1, "maxLength": 64, "pattern": "^[a-z0-9][a-z0-9-_]*$"},
    "title": {"type": "string", "maxLength": 120},
    "x": {"type": "number"},
    "y": {"type": "number"},
    "w": {"type": "number", "minimum": 80, "maximum": 4000},
    "h": {"type": "number", "minimum": 60, "maximum": 4000},
    "z": {"type": "integer", "minimum": -(2**53 - 1), "maximum": 2**53 - 1},
    "code": {"type": "string", "minLength": 1, "maxLength": 200_000},
    "codeVersion": {"type": "integer"},
    "surface": {"type": "string", "enum": ["card", "plain"]},
    "hidden": {"type": "boolean"},
}


def fragment_schema(*, hydrated: bool) -> dict[str, Any]:
    properties = dict(FRAGMENT_PROPERTIES)
    code_key = "code" if hydrated else "codeRef"
    if not hydrated:
        properties.pop("code")
        properties["codeRef"] = {"type": "string", "minLength": 64, "maxLength": 64}
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["id", "x", "y", "w", "h", code_key],
        "properties": properties,
    }


def snapshot_schema(*, hydrated: bool) -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["schemaVersion"],
        "properties": {
            "schemaVersion": {"type": "integer", "enum": [1]},
            "fragments": {
                "type": "array",
                "maxItems": MAX_COLLECTION_ITEMS,
                "items": fragment_schema(hydrated=hydrated),
            },
            "state": {
                "type": "object",
                "maxProperties": MAX_COLLECTION_ITEMS,
                "propertyNames": STATE_KEY_SCHEMA,
                "additionalProperties": STATE_VALUE_SCHEMA,
            },
        },
    }


def patch_schema(fragment: dict[str, Any]) -> dict[str, Any]:
    return {
        **fragment,
        "required": [],
        "properties": {key: value for key, value in fragment["properties"].items() if key != "id"},
    }


FRAGMENT_SCHEMA = fragment_schema(hydrated=True)
READ_FRAGMENT_SCHEMA = fragment_schema(hydrated=False)
SNAPSHOT_SCHEMA = snapshot_schema(hydrated=True)
READ_SNAPSHOT_SCHEMA = snapshot_schema(hydrated=False)
OP_PROPERTIES: dict[str, dict[str, Any]] = {
    "add_fragment": {"fragment": FRAGMENT_SCHEMA},
    "update_fragment": {
        "id": {"type": "string"},
        "patch": patch_schema(FRAGMENT_SCHEMA),
    },
    "remove_fragment": {"id": {"type": "string"}},
    "bring_to_front": {"id": {"type": "string"}},
    "set_state": {"key": STATE_KEY_SCHEMA, "value": STATE_VALUE_SCHEMA},
    "restore": {
        "snapshot": SNAPSHOT_SCHEMA,
        "toSeq": {"type": "integer"},
        "expectedSeq": {"type": "integer", "minimum": 0},
    },
    "edit_field": {
        "key": STATE_KEY_SCHEMA,
        "kind": FIELD_KIND_SCHEMA,
        "initialValue": {},
        "insert": {
            "type": "array",
            "maxItems": MAX_COLLECTION_ITEMS,
            "items": {
                "type": "object",
                "required": ["id", "k", "v"],
                "properties": {"id": FIELD_ID_SCHEMA, **FIELD_ENTRY_PROPERTIES},
            },
        },
        "remove": {"type": "array", "maxItems": MAX_COLLECTION_ITEMS, "items": FIELD_ID_SCHEMA},
    },
}
OP_SCHEMAS: dict[str, dict[str, Any]] = {
    kind: {
        "type": "object",
        "required": [
            "type",
            *(key for key in properties if key not in {"insert", "remove", "initialValue", "expectedSeq"}),
        ],
        "properties": {"type": {"type": "string", "const": kind}, **properties},
    }
    for kind, properties in OP_PROPERTIES.items()
}
OP_SCHEMA = {"oneOf": list(OP_SCHEMAS.values())}
READ_OP_PROPERTIES = {
    "add_fragment": {"fragment": READ_FRAGMENT_SCHEMA},
    "update_fragment": {"patch": patch_schema(READ_FRAGMENT_SCHEMA)},
    "restore": {"snapshot": READ_SNAPSHOT_SCHEMA},
}
READ_OP_SCHEMA = {
    "oneOf": [
        {**schema, "properties": {**schema["properties"], **READ_OP_PROPERTIES.get(kind, {})}}
        for kind, schema in OP_SCHEMAS.items()
    ]
}
OP_VALIDATORS = {kind: Draft202012Validator(schema) for kind, schema in OP_SCHEMAS.items()}
MAX_SKETCHPAD_OP_BYTES = 256 * 1024


def validate_op(op: Any) -> None:
    if not isinstance(op, dict):
        raise ValidationError("Each op must be a JSON object.")
    op_type = op.get("type")
    if not isinstance(op_type, str) or op_type not in OP_VALIDATORS:
        raise ValidationError(f"op.type must be one of: {', '.join(OP_VALIDATORS)}.")
    limit = settings.DATA_UPLOAD_MAX_MEMORY_SIZE if op_type == "restore" else MAX_SKETCHPAD_OP_BYTES
    if limit is not None and len(json.dumps(op, separators=(",", ":"), ensure_ascii=False).encode()) > limit:
        raise ValidationError(f"This operation is capped at {limit // 1024} KB serialized.")
    if not OP_VALIDATORS[op_type].is_valid(op):
        raise ValidationError("Invalid sketchpad operation. Check the required fields, types, and limits.")
