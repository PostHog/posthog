import logging
from typing import Any, Optional, Set
from rest_framework import serializers

from posthog.hogql.bytecode import create_bytecode
from posthog.hogql.parser import parse_program
from posthog.models.hog_functions.utils import generate_template_bytecode

logger = logging.getLogger(__name__)


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

        if schema.get("required") and not value:
            raise serializers.ValidationError("This field is required.")

        if not value:
            return attrs

        name: str = schema["key"]
        item_type = schema["type"]
        value = attrs["value"]

        # Validate each type
        if item_type == "string":
            if not isinstance(value, str):
                raise serializers.ValidationError("Value must be a string.")
        elif item_type == "boolean":
            if not isinstance(value, bool):
                raise serializers.ValidationError("Value must be a boolean.")
        elif item_type == "dictionary":
            if not isinstance(value, dict):
                raise serializers.ValidationError("Value must be a dictionary.")

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
            first_error = next(iter(serializer.errors.values()))[0]
            raise serializers.ValidationError({"inputs": {schema["key"]: first_error}})

        validated_inputs[schema["key"]] = serializer.validated_data

    return validated_inputs


def compile_hog(hog: str, supported_functions: Optional[set[str]] = None) -> list[Any]:
    # Attempt to compile the hog
    try:
        program = parse_program(hog)
        return create_bytecode(program, supported_functions=supported_functions or {"fetch"})
    except Exception as e:
        raise serializers.ValidationError({"hog": "Hog code has errors." + str(e)})
