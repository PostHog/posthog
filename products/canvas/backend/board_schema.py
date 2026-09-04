import json
from typing import Any

from django.conf import settings
from django.core.exceptions import ValidationError

from jsonschema import Draft202012Validator

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
                "propertyNames": FIELD_ID_SCHEMA,
                "additionalProperties": {
                    "type": "object",
                    "required": ["k", "v"],
                    "properties": FIELD_ENTRY_PROPERTIES,
                },
            },
            "removed": {"type": "array", "items": FIELD_ID_SCHEMA},
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
    "z": {"type": "integer"},
    "code": {"type": "string", "minLength": 1, "maxLength": 200_000},
    "codeVersion": {"type": "integer"},
    "surface": {"type": "string", "enum": ["card", "plain"]},
    "hidden": {"type": "boolean"},
}
FRAGMENT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["id", "x", "y", "w", "h", "code"],
    "properties": FRAGMENT_PROPERTIES,
}
SNAPSHOT_PROPERTIES = {
    "schemaVersion": {"type": "integer", "enum": [1]},
    "fragments": {"type": "array", "items": FRAGMENT_SCHEMA},
    "state": {"type": "object", "propertyNames": STATE_KEY_SCHEMA, "additionalProperties": STATE_VALUE_SCHEMA},
}
SNAPSHOT_SCHEMA = {
    "type": "object",
    "required": ["schemaVersion"],
    "properties": SNAPSHOT_PROPERTIES,
}
READ_SNAPSHOT_SCHEMA = {
    **SNAPSHOT_SCHEMA,
    "properties": {
        **SNAPSHOT_PROPERTIES,
        "fragments": {
            "type": "array",
            "items": {
                "oneOf": [
                    FRAGMENT_SCHEMA,
                    {
                        "type": "object",
                        "required": ["id", "x", "y", "w", "h", "codeRef"],
                        "properties": {
                            **{key: value for key, value in FRAGMENT_PROPERTIES.items() if key != "code"},
                            "codeRef": {"type": "string", "minLength": 64, "maxLength": 64},
                        },
                        "additionalProperties": False,
                    },
                ]
            },
        },
    },
}
OP_PROPERTIES: dict[str, dict[str, Any]] = {
    "add_fragment": {"fragment": FRAGMENT_SCHEMA},
    "update_fragment": {
        "id": {"type": "string"},
        "patch": {
            "type": "object",
            "additionalProperties": False,
            "properties": {key: value for key, value in FRAGMENT_PROPERTIES.items() if key != "id"},
        },
    },
    "remove_fragment": {"id": {"type": "string"}},
    "bring_to_front": {"id": {"type": "string"}},
    "set_state": {"key": STATE_KEY_SCHEMA, "value": STATE_VALUE_SCHEMA},
    "restore": {"snapshot": SNAPSHOT_SCHEMA, "toSeq": {"type": "integer"}},
    "edit_field": {
        "key": STATE_KEY_SCHEMA,
        "kind": FIELD_KIND_SCHEMA,
        "insert": {
            "type": "array",
            "maxItems": 2000,
            "items": {
                "type": "object",
                "required": ["id", "k", "v"],
                "properties": {"id": FIELD_ID_SCHEMA, **FIELD_ENTRY_PROPERTIES},
            },
        },
        "remove": {"type": "array", "maxItems": 2000, "items": FIELD_ID_SCHEMA},
    },
}
OP_SCHEMAS = {
    kind: {
        "type": "object",
        "required": ["type", *(key for key in properties if key not in {"insert", "remove"})],
        "properties": {"type": {"type": "string", "enum": [kind]}, **properties},
    }
    for kind, properties in OP_PROPERTIES.items()
}
OP_SCHEMA = {"oneOf": list(OP_SCHEMAS.values())}
OP_VALIDATORS = {kind: Draft202012Validator(schema) for kind, schema in OP_SCHEMAS.items()}
SNAPSHOT_VALIDATOR = Draft202012Validator(SNAPSHOT_SCHEMA)
MAX_BOARD_OP_BYTES = 256 * 1024


def validate_op(op: Any) -> None:
    if not isinstance(op, dict):
        raise ValidationError("Each op must be a JSON object.")
    op_type = op.get("type")
    if not isinstance(op_type, str) or op_type not in OP_VALIDATORS:
        raise ValidationError(f"op.type must be one of: {', '.join(OP_VALIDATORS)}.")
    limit = settings.DATA_UPLOAD_MAX_MEMORY_SIZE if op_type == "restore" else MAX_BOARD_OP_BYTES
    if limit is not None and len(json.dumps(op, separators=(",", ":"))) > limit:
        raise ValidationError(f"This operation is capped at {limit // 1024} KB serialized.")
    if not OP_VALIDATORS[op_type].is_valid(op):
        raise ValidationError("Invalid board operation. Check the required fields, types, and limits.")


def validate_snapshot(snapshot: object) -> None:
    if not SNAPSHOT_VALIDATOR.is_valid(snapshot):
        raise ValidationError("Invalid board snapshot. Check the required fields, types, and limits.")
