from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from google.genai.types import Type as _TypeEnum
else:
    _TypeEnum = Any


def get_type_enum(json_type: str) -> _TypeEnum:
    from posthog.api.wizard.genai_types import get_genai_type

    type_class = get_genai_type("TypeEnum")

    """Convert JSON Schema type to Gemini Type enum"""
    type_mapping = {
        "string": type_class.STRING,
        "number": type_class.NUMBER,
        "integer": type_class.INTEGER,
        "boolean": type_class.BOOLEAN,
        "array": type_class.ARRAY,
        "object": type_class.OBJECT,
    }
    return type_mapping.get(json_type, type_class.STRING)


def get_field_mappings() -> dict[str, str]:
    """Get mappings from JSON Schema field names to Gemini schema field names"""
    return {
        "description": "description",
        "default": "default",
        "enum": "enum",
        "pattern": "pattern",
        "minLength": "min_length",
        "maxLength": "max_length",
        "minimum": "minimum",
        "maximum": "maximum",
        "minItems": "min_items",
        "maxItems": "max_items",
        "minProperties": "min_properties",
        "maxProperties": "max_properties",
        "required": "required",
        "nullable": "nullable",
        "title": "title",
        "example": "example",
    }


def convert_schema(schema: dict) -> dict[str, Any]:
    """Convert a single schema object from JSON Schema to Gemini format"""
    result: dict[str, Any] = {}

    if "type" in schema:
        result["type"] = get_type_enum(schema["type"])

    field_mappings = get_field_mappings()
    for json_field, gemini_field in field_mappings.items():
        if json_field in schema:
            result[gemini_field] = schema[json_field]

    if "format" in schema:
        result["format"] = schema["format"]

    if "properties" in schema:
        result["properties"] = {key: convert_schema(value) for key, value in schema["properties"].items()}

    if "items" in schema:
        result["items"] = convert_schema(schema["items"])

    if "anyOf" in schema:
        result["any_of"] = [convert_schema(s) for s in schema["anyOf"]]

    return result


def json_schema_to_gemini_schema(json_schema: dict) -> dict[str, Any]:
    """Convert JSON Schema to Gemini Schema format"""
    actual_schema = json_schema.get("schema", json_schema)

    return convert_schema(actual_schema)
