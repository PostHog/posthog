from unittest import TestCase

from google.genai.types import Type

from ..utils import convert_schema, json_schema_to_gemini_schema


class TestSchemaConversion(TestCase):
    def test_convert_schema_basic_types(self):
        string_schema = {"type": "string"}
        result = convert_schema(string_schema)
        assert result["type"] == Type.STRING

        number_schema = {"type": "number"}
        result = convert_schema(number_schema)
        assert result["type"] == Type.NUMBER

        integer_schema = {"type": "integer"}
        result = convert_schema(integer_schema)
        assert result["type"] == Type.INTEGER

    def test_convert_schema_with_properties(self):
        schema = {
            "type": "object",
            "properties": {"name": {"type": "string"}, "age": {"type": "integer"}},
            "required": ["name"],
        }
        result = convert_schema(schema)

        assert result["type"] == Type.OBJECT
        assert "properties" in result
        assert result["properties"]["name"]["type"] == Type.STRING
        assert result["properties"]["age"]["type"] == Type.INTEGER
        assert result["required"] == ["name"]

    def test_convert_schema_with_array(self):
        schema = {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 10}
        result = convert_schema(schema)

        assert result["type"] == Type.ARRAY
        assert result["items"]["type"] == Type.STRING
        assert result["min_items"] == 1
        assert result["max_items"] == 10

    def test_convert_schema_with_constraints(self):
        schema = {
            "type": "string",
            "minLength": 5,
            "maxLength": 50,
            "pattern": r"^[a-zA-Z]+$",
            "description": "A name field",
            "default": "Anonymous",
        }
        result = convert_schema(schema)

        assert result["type"] == Type.STRING
        assert result["min_length"] == 5
        assert result["max_length"] == 50
        assert result["pattern"] == r"^[a-zA-Z]+$"
        assert result["description"] == "A name field"
        assert result["default"] == "Anonymous"

    def test_convert_schema_with_anyof(self):
        schema = {"anyOf": [{"type": "string"}, {"type": "number"}]}
        result = convert_schema(schema)

        assert "any_of" in result
        assert len(result["any_of"]) == 2
        assert result["any_of"][0]["type"] == Type.STRING
        assert result["any_of"][1]["type"] == Type.NUMBER

    def test_json_schema_to_gemini_schema_wrapped_format(self):
        input_schema = {
            "schema": {
                "type": "object",
                "properties": {"files": {"type": "array", "items": {"type": "string"}}},
                "required": ["files"],
                "additionalProperties": False,
            },
            "name": "schema",
            "strict": True,
        }

        result = json_schema_to_gemini_schema(input_schema)

        assert result["type"] == Type.OBJECT
        assert "properties" in result
        assert "files" in result["properties"]
        assert result["properties"]["files"]["type"] == Type.ARRAY
        assert result["properties"]["files"]["items"]["type"] == Type.STRING
        assert result["required"] == ["files"]

    def test_json_schema_to_gemini_schema_direct_format(self):
        direct_schema = {
            "type": "object",
            "properties": {"name": {"type": "string"}, "age": {"type": "integer"}},
            "required": ["name"],
        }

        result = json_schema_to_gemini_schema(direct_schema)

        assert result["type"] == Type.OBJECT
        assert "properties" in result
        assert result["properties"]["name"]["type"] == Type.STRING
        assert result["properties"]["age"]["type"] == Type.INTEGER
        assert result["required"] == ["name"]

    def test_complex_nested_schema(self):
        complex_schema = {
            "type": "object",
            "properties": {
                "user": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "minLength": 1},
                        "email": {"type": "string", "format": "email"},
                        "tags": {"type": "array", "items": {"type": "string"}, "minItems": 0, "maxItems": 5},
                    },
                    "required": ["name", "email"],
                },
                "metadata": {
                    "type": "object",
                    "properties": {
                        "created": {"type": "string", "format": "date-time"},
                        "version": {"type": "number", "minimum": 1},
                    },
                },
            },
            "required": ["user"],
        }

        result = json_schema_to_gemini_schema(complex_schema)

        assert result["type"] == Type.OBJECT
        assert result["required"] == ["user"]

        # Check user object
        user_schema = result["properties"]["user"]
        assert user_schema["type"] == Type.OBJECT
        assert user_schema["required"] == ["name", "email"]
        assert user_schema["properties"]["name"]["type"] == Type.STRING
        assert user_schema["properties"]["name"]["min_length"] == 1
        assert user_schema["properties"]["email"]["type"] == Type.STRING
        assert user_schema["properties"]["email"]["format"] == "email"

        # Check tags array
        tags_schema = user_schema["properties"]["tags"]
        assert tags_schema["type"] == Type.ARRAY
        assert tags_schema["items"]["type"] == Type.STRING
        assert tags_schema["min_items"] == 0
        assert tags_schema["max_items"] == 5

        # Check metadata object
        metadata_schema = result["properties"]["metadata"]
        assert metadata_schema["type"] == Type.OBJECT
        assert metadata_schema["properties"]["created"]["type"] == Type.STRING
        assert metadata_schema["properties"]["created"]["format"] == "date-time"
        assert metadata_schema["properties"]["version"]["type"] == Type.NUMBER
        assert metadata_schema["properties"]["version"]["minimum"] == 1
