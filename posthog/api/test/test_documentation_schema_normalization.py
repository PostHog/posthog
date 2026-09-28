from typing import Any

import pytest

from posthog.api.documentation.schema_normalization import _fix_pydantic_schema_for_openapi


@pytest.mark.parametrize(
    "_name,schema,expected",
    [
        ("not_a_dict", "string", "string"),
        ("nullable_string_type", {"type": "string", "nullable": True}, {"type": ["string", "null"]}),
        (
            "nullable_type_list",
            {"type": ["string", "integer"], "nullable": True},
            {"type": ["string", "integer", "null"]},
        ),
        ("nullable_type_list_with_null", {"type": ["string", "null"], "nullable": True}, {"type": ["string", "null"]}),
        ("nullable_ref", {"$ref": "#/X", "nullable": True}, {"oneOf": [{"$ref": "#/X"}, {"type": "null"}]}),
        (
            "nullable_one_of",
            {"oneOf": [{"$ref": "#/X"}], "nullable": True},
            {"oneOf": [{"$ref": "#/X"}, {"type": "null"}]},
        ),
        (
            "nullable_any_of_with_null",
            {"anyOf": [{"type": "string"}, {"type": "null"}], "nullable": True},
            {"anyOf": [{"type": "string"}, {"type": "null"}]},
        ),
        ("bare_nullable", {"nullable": True}, {}),
        ("nullable_false_dropped", {"type": "string", "nullable": False}, {"type": "string"}),
        ("bare_nullable_any_one_of", {"oneOf": [{}, {"type": "null"}]}, {}),
        ("bare_nullable_any_any_of", {"anyOf": [{"type": "null"}, {}]}, {}),
        (
            "empty_additional_properties",
            {"type": "object", "additionalProperties": {}},
            {"type": "object", "additionalProperties": True},
        ),
        (
            "nested_additional_properties",
            {"type": "object", "additionalProperties": {"type": "string", "nullable": True}},
            {"type": "object", "additionalProperties": {"type": ["string", "null"]}},
        ),
        (
            "nested_properties_and_items",
            {
                "type": "object",
                "properties": {
                    "a": {"type": "array", "items": {"allOf": [{"$ref": "#/A"}]}},
                    "b": {"type": "array", "items": [{"type": "integer", "nullable": True}]},
                },
            },
            {
                "type": "object",
                "properties": {
                    "a": {"type": "array", "items": {"$ref": "#/A"}},
                    "b": {"type": "array", "items": [{"type": ["integer", "null"]}]},
                },
            },
        ),
        (
            "ref_only_bounds_stripped",
            {"allOf": [{"$ref": "#/Enum"}], "minimum": 0, "maximum": 5, "description": "d"},
            {"allOf": [{"$ref": "#/Enum"}], "description": "d"},
        ),
        (
            "typed_bounds_kept",
            {"type": "integer", "minimum": 0, "maximum": 5},
            {"type": "integer", "minimum": 0, "maximum": 5},
        ),
        ("single_all_of_collapsed", {"allOf": [{"$ref": "#/A"}], "minimum": 0}, {"$ref": "#/A"}),
        (
            "multi_all_of_kept",
            {"allOf": [{"$ref": "#/A"}, {"$ref": "#/B"}]},
            {"allOf": [{"$ref": "#/A"}, {"$ref": "#/B"}]},
        ),
        (
            "nested_combinators",
            {"oneOf": [{"type": "string", "nullable": True}], "anyOf": [{"allOf": [{"$ref": "#/A"}]}]},
            {"oneOf": [{"type": ["string", "null"]}], "anyOf": [{"$ref": "#/A"}]},
        ),
    ],
)
def test_fix_pydantic_schema_for_openapi(_name: str, schema: Any, expected: Any) -> None:
    assert _fix_pydantic_schema_for_openapi(schema) == expected


def test_fix_pydantic_schema_for_openapi_does_not_mutate_input() -> None:
    schema = {"type": "string", "nullable": True}

    _fix_pydantic_schema_for_openapi(schema)

    assert schema == {"type": "string", "nullable": True}
