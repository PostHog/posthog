import logging
from typing import Any, Optional
from rest_framework import serializers

from posthog.hogql.bytecode import create_bytecode
from posthog.hogql.parser import parse_program, parse_string_template

logger = logging.getLogger(__name__)


def generate_template_bytecode(obj: Any) -> Any:
    """
    Clones an object, compiling any string values to bytecode templates
    """

    if isinstance(obj, dict):
        return {key: generate_template_bytecode(value) for key, value in obj.items()}
    elif isinstance(obj, list):
        return [generate_template_bytecode(item) for item in obj]
    elif isinstance(obj, str):
        return create_bytecode(parse_string_template(obj))
    else:
        return obj


class InputsSchemaItemSerializer(serializers.Serializer):
    type = serializers.ChoiceField(choices=["string", "boolean", "dictionary", "choice", "json"])
    key = serializers.CharField()
    label = serializers.CharField(required=False)  # type: ignore
    choices = serializers.ListField(child=serializers.DictField(), required=False)
    required = serializers.BooleanField(default=False)  # type: ignore
    default = serializers.JSONField(required=False)
    secret = serializers.BooleanField(default=False)
    description = serializers.CharField(required=False)

    # TODO Validate choices if type=choice


class AnyInputField(serializers.Field):
    def to_internal_value(self, data):
        return data

    def to_representation(self, value):
        return value


class InputsItemSerializer(serializers.Serializer):
    value = AnyInputField(required=False)
    bytecode = serializers.ListField(required=False, read_only=True)

    def validate(self, attrs):
        schema = self.context["schema"]
        value = attrs.get("value")

        name: str = schema["key"]
        item_type = schema["type"]

        if schema.get("required") and not value:
            raise serializers.ValidationError({"inputs": {name: f"This field is required."}})

        if not value:
            return attrs

        # Validate each type
        if item_type == "string":
            if not isinstance(value, str):
                raise serializers.ValidationError({"inputs": {name: f"Value must be a string."}})
        elif item_type == "boolean":
            if not isinstance(value, bool):
                raise serializers.ValidationError({"inputs": {name: f"Value must be a boolean."}})
        elif item_type == "dictionary":
            if not isinstance(value, dict):
                raise serializers.ValidationError({"inputs": {name: f"Value must be a dictionary."}})

        try:
            if value:
                if item_type in ["string", "dictionary", "json"]:
                    attrs["bytecode"] = generate_template_bytecode(value)
        except Exception as e:
            raise serializers.ValidationError({"inputs": {name: f"Invalid template: {str(e)}"}})

        return attrs


def validate_inputs_schema(value: list) -> list:
    if not isinstance(value, list):
        raise serializers.ValidationError("inputs_schema must be a list of objects.")

    serializer = InputsSchemaItemSerializer(data=value, many=True)

    if not serializer.is_valid():
        raise serializers.ValidationError(serializer.errors)

    return serializer.validated_data or []


def validate_inputs(inputs_schema: list, inputs: dict) -> dict:
    validated_inputs = {}

    for schema in inputs_schema:
        value = inputs.get(schema["key"], {})
        serializer = InputsItemSerializer(data=value, context={"schema": schema})

        if not serializer.is_valid():
            raise serializers.ValidationError(serializer.errors)

        validated_inputs[schema["key"]] = serializer.validated_data

    return validated_inputs


def compile_hog(hog: str, supported_functions: Optional[set[str]] = None) -> list[Any]:
    # Attempt to compile the hog
    try:
        program = parse_program(hog)
        return create_bytecode(program, supported_functions=supported_functions or {"fetch"})
    except Exception as e:
        logger.error(f"Failed to compile hog {e}", exc_info=True)
        raise serializers.ValidationError({"hog": "Hog code has errors."})
