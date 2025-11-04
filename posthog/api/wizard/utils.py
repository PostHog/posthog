from __future__ import annotations

from google.genai.types import Type


def get_type_enum(json_type: str) -> Type:
    """Convert JSON Schema type to Gemini Type enum"""
    type_mapping = {
        "string": Type.STRING,
        "number": Type.NUMBER,
        "integer": Type.INTEGER,
        "boolean": Type.BOOLEAN,
        "array": Type.ARRAY,
        "object": Type.OBJECT,
    }
    return type_mapping.get(json_type, Type.STRING)


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


def convert_schema(schema: dict) -> dict:
    """Convert a single schema object from JSON Schema to Gemini format"""
    result = {}

    if "type" in schema:
        result["type"] = get_type_enum(schema["type"])

    field_mappings = get_field_mappings()
    for json_field, gemini_field in field_mappings.items():
        if json_field in schema:
            result[gemini_field] = schema[json_field]

    if "format" in schema:
        result["format"] = schema["format"]

    if "properties" in schema:
        result["properties"] = {key: convert_schema(value) for key, value in schema["properties"].items()}  # type: ignore

    if "items" in schema:
        result["items"] = convert_schema(schema["items"])  # type: ignore

    if "anyOf" in schema:
        result["any_of"] = [convert_schema(s) for s in schema["anyOf"]]  # type: ignore

    return result


def json_schema_to_gemini_schema(json_schema: dict) -> dict:
    """Convert JSON Schema to Gemini Schema format"""
    actual_schema = json_schema.get("schema", json_schema)

    return convert_schema(actual_schema)
