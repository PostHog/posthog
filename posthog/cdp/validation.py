import json
import logging
from typing import Any, Optional
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from posthog.cdp.filters import compile_filters_bytecode, compile_filters_expr
from posthog.hogql.compiler.bytecode import create_bytecode
from posthog.hogql.compiler.javascript import JavaScriptCompiler
from posthog.hogql.parser import parse_program, parse_string_template
from posthog.hogql.visitor import TraversingVisitor
from posthog.models.hog_functions.hog_function import (
    TYPES_WITH_COMPILED_FILTERS,
    TYPES_WITH_JAVASCRIPT_SOURCE,
    TYPES_WITH_TRANSPILED_FILTERS,
)
from posthog.hogql import ast

logger = logging.getLogger(__name__)


class InputCollector(TraversingVisitor):
    inputs: set[str]

    def __init__(self):
        super().__init__()
        self.inputs = set()

    def visit_field(self, node: ast.Field):
        super().visit_field(node)
        if node.chain[0] == "inputs":
            if len(node.chain) > 1:
                self.inputs.add(str(node.chain[1]))


def collect_inputs(node: ast.Expr) -> set[str]:
    input_collector = InputCollector()
    input_collector.visit(node)
    return input_collector.inputs


def generate_template_bytecode(obj: Any, input_collector: set[str]) -> Any:
    """
    Clones an object, compiling any string values to bytecode templates
    """

    if isinstance(obj, dict):
        return {key: generate_template_bytecode(value, input_collector) for key, value in obj.items()}
    elif isinstance(obj, list):
        return [generate_template_bytecode(item, input_collector) for item in obj]
    elif isinstance(obj, str):
        node = parse_string_template(obj)
        input_collector.update(collect_inputs(node))
        return create_bytecode(node).bytecode
    else:
        return obj


def transpile_template_code(obj: Any, compiler: JavaScriptCompiler) -> str:
    """
    Clones an object, compiling any string values to bytecode templates
    """
    if isinstance(obj, dict):
        return (
            "{"
            + (
                ", ".join(
                    [
                        f"{json.dumps(str(key))}: {transpile_template_code(value, compiler)}"
                        for key, value in obj.items()
                    ]
                )
            )
            + "}"
        )
    elif isinstance(obj, list):
        return "[" + (", ".join([transpile_template_code(item, compiler) for item in obj])) + "]"
    elif isinstance(obj, str):
        return compiler.visit(parse_string_template(obj))
    else:
        return json.dumps(obj)


class InputsSchemaItemSerializer(serializers.Serializer):
    type = serializers.ChoiceField(
        choices=[
            "string",
            "number",
            "boolean",
            "dictionary",
            "choice",
            "json",
            "integration",
            "integration_field",
            "email",
        ]
    )
    key = serializers.CharField()
    label = serializers.CharField(required=False, allow_blank=True)  # type: ignore
    choices = serializers.ListField(child=serializers.DictField(), required=False)
    required = serializers.BooleanField(default=False)  # type: ignore
    default = serializers.JSONField(required=False)
    secret = serializers.BooleanField(default=False)
    hidden = serializers.BooleanField(default=False)
    description = serializers.CharField(required=False)
    integration = serializers.CharField(required=False)
    integration_key = serializers.CharField(required=False)
    requires_field = serializers.CharField(required=False)
    integration_field = serializers.CharField(required=False)
    requiredScopes = serializers.CharField(required=False)
    # Indicates if hog templating should be used for this input
    templating = serializers.BooleanField(required=False)

    # TODO Validate choices if type=choice


class AnyInputField(serializers.Field):
    def to_internal_value(self, data):
        return data

    def to_representation(self, value):
        return value


class InputsItemSerializer(serializers.Serializer):
    value = AnyInputField(required=False)
    templating = serializers.ChoiceField(choices=["hog", "liquid"], required=False)
    bytecode = serializers.ListField(required=False, read_only=True)
    order = serializers.IntegerField(required=False, read_only=True)
    transpiled = serializers.JSONField(required=False, read_only=True)

    def to_representation(self, value):
        # We want to override the way this gets rendered as the underlying serializer is a DictField which does weird things
        return {k: v for k, v in value.items() if v is not None}

    def validate(self, attrs):
        schema = self.context["schema"]
        function_type = self.context["function_type"]
        value = attrs.get("value")
        item_type = schema["type"]

        if schema.get("required") and (value is None or value == ""):
            raise serializers.ValidationError({"input": f"This field is required."})

        if not value:
            return attrs

        # Validate each type
        if item_type == "string":
            if not isinstance(value, str):
                raise serializers.ValidationError({"input": f"Value must be a string."})
        elif item_type == "number":
            if not isinstance(value, int | float):
                raise serializers.ValidationError({"input": f"Value must be a number."})
        elif item_type == "boolean":
            if not isinstance(value, bool):
                raise serializers.ValidationError({"input": f"Value must be a boolean."})
        elif item_type == "dictionary":
            if not isinstance(value, dict):
                raise serializers.ValidationError({"input": f"Value must be a dictionary."})
        elif item_type == "integration":
            if not isinstance(value, int):
                raise serializers.ValidationError({"input": f"Value must be an Integration ID."})
        elif item_type == "email":
            if not isinstance(value, dict):
                raise serializers.ValidationError({"input": f"Value must be an email object."})
            for key_ in ["from", "to", "subject"]:
                if not value.get(key_):
                    raise serializers.ValidationError({"input": f"Missing value for '{key_}'."})

            if not value.get("text") and not value.get("html"):
                raise serializers.ValidationError({"input": f"Either 'text' or 'html' is required."})

        try:
            if value and schema.get("templating", True):
                if attrs.get("templating") == "liquid":
                    # NOTE: We don't do validaton at this level. The frontend will validate for us
                    # and we don't care about it being invalid at this stage.
                    pass
                else:
                    # If we have a value and hog templating is enabled, we need to transpile the value
                    if item_type in ["string", "dictionary", "json", "email"]:
                        if item_type == "email" and isinstance(value, dict):
                            # We want to exclude the "design" property
                            value = {key: value[key] for key in value if key != "design"}

                        if function_type in TYPES_WITH_JAVASCRIPT_SOURCE:
                            compiler = JavaScriptCompiler()
                            code = transpile_template_code(value, compiler)
                            attrs["transpiled"] = {"lang": "ts", "code": code, "stl": list(compiler.stl_functions)}
                            if "bytecode" in attrs:
                                del attrs["bytecode"]
                        else:
                            input_collector: set[str] = set()
                            attrs["bytecode"] = generate_template_bytecode(value, input_collector)
                            attrs["input_deps"] = list(input_collector)
                            if "transpiled" in attrs:
                                del attrs["transpiled"]
        except Exception as e:
            raise serializers.ValidationError({"input": f"Invalid template: {str(e)}"})

        return attrs


class InputsSerializer(serializers.DictField):
    """
    Provides the same typing as the DictField but with custom validation to only include the inputs that are in the schema
    """

    child = InputsItemSerializer()

    def run_child_validation(self, data):
        result = {}
        errors = {}

        existing_secret_inputs = self.context.get("encrypted_inputs")
        # Note this should always be the child of a dict serializer with a sibling 'inputs_schema' field so we can validate against the relevant schema
        parent_serializer = self.parent
        try:
            inputs_schema = parent_serializer.initial_data["inputs_schema"]
        except:
            raise serializers.ValidationError("Missing inputs_schema.")

        # Validate each input against the schema
        for schema in inputs_schema:
            key = str(schema["key"])
            value = data.get(key) or {}

            # We only load the existing secret if the schema is secret and the given value has "secret" set
            if schema.get("secret") and existing_secret_inputs and ((value and value.get("secret")) or value == {}):
                value = existing_secret_inputs.get(schema["key"]) or {}

            self.context["schema"] = schema

            try:
                input_value = self.child.run_validation(value)

                if "value" not in input_value:
                    # Indicates no value is provided and no error was thrown which is fine so we can exclude it
                    continue

                result[key] = input_value
            except ValidationError as e:
                # TRICKY: Need to get the nested error message to ensure the structure is correct
                if "input" in e.detail and isinstance(e.detail, dict):
                    errors[key] = e.detail.get("input")
                else:
                    errors[key] = e.detail

        if errors:
            raise ValidationError(errors)

        # We'll topologically sort keys based on their input_deps.
        edges = {}
        all_keys = list(result.keys())
        for k, v in result.items():
            deps = v.get("input_deps", [])
            deps = [d for d in deps if d in result]
            edges[k] = deps

        sorted_keys = topological_sort(all_keys, edges)

        # Assign order according to topological sort
        for i, key in enumerate(sorted_keys):
            result[key]["order"] = i
            if "input_deps" in result[key]:
                del result[key]["input_deps"]

        # Rebuild in sorted order
        result = {key: result[key] for key in sorted_keys}

        return result
        # Unlike standard dict validation we are iterating the schema - not the inputs


class HogFunctionFiltersSerializer(serializers.Serializer):
    actions = serializers.ListField(child=serializers.DictField(), required=False)
    events = serializers.ListField(child=serializers.DictField(), required=False)
    properties = serializers.ListField(child=serializers.DictField(), required=False)
    bytecode = serializers.JSONField(required=False, allow_null=True)
    transpiled = serializers.JSONField(required=False)
    filter_test_accounts = serializers.BooleanField(required=False)
    bytecode_error = serializers.CharField(required=False)

    def to_internal_value(self, data):
        # Weirdly nested serializers don't get this set...
        self.initial_data = data
        return super().to_internal_value(data)

    def validate(self, data):
        function_type = self.context["function_type"]
        team = self.context["get_team"]()

        # Ensure data is initialized as an empty dict if it's None
        data = data or {}

        # If we have a bytecode, we need to validate the transpiled
        if function_type in TYPES_WITH_COMPILED_FILTERS:
            data = compile_filters_bytecode(data, team)
            # Check if bytecode compilation resulted in an error
            if data.get("bytecode_error"):
                raise serializers.ValidationError(f"Invalid filter configuration: {data['bytecode_error']}")
        elif function_type in TYPES_WITH_TRANSPILED_FILTERS:
            compiler = JavaScriptCompiler()
            code = compiler.visit(compile_filters_expr(data, team))
            data["transpiled"] = {"lang": "ts", "code": code, "stl": list(compiler.stl_functions)}
            if "bytecode" in data:
                del data["bytecode"]
        return data


class MappingsSerializer(serializers.Serializer):
    name = serializers.CharField(required=False)
    inputs_schema = serializers.ListField(child=InputsSchemaItemSerializer(), required=False)
    inputs = InputsSerializer(required=False)
    filters = HogFunctionFiltersSerializer(required=False)

    def to_internal_value(self, data):
        # Weirdly nested serializers don't get this set...
        self.initial_data = data
        return super().to_internal_value(data)


def topological_sort(nodes: list[str], edges: dict[str, list[str]]) -> list[str]:
    """
    Perform a topological sort on the given graph.
    nodes: list of all node identifiers
    edges: adjacency list where edges[node] = list of nodes that `node` depends on
    Returns: A list of nodes in topologically sorted order (no cycles).
    Raises an error if a cycle is detected.
    """
    # Build in-degree
    in_degree = {node: 0 for node in nodes}
    for node, deps in edges.items():
        for dep in deps:
            if dep in in_degree:
                in_degree[node] = in_degree[node] + 1

    # Find all nodes with in_degree 0
    queue = [n for n, d in in_degree.items() if d == 0]
    sorted_list = []

    while queue:
        current = queue.pop(0)
        sorted_list.append(current)
        # Decrease in-degree of dependent nodes
        for node, deps in edges.items():
            if current in deps:
                in_degree[node] -= 1
                if in_degree[node] == 0:
                    queue.append(node)

    if len(sorted_list) != len(nodes):
        raise serializers.ValidationError("Circular dependency detected in input_deps.")

    return sorted_list


def compile_hog(hog: str, hog_type: str, in_repl: Optional[bool] = False) -> list[Any]:
    # Attempt to compile the hog
    try:
        program = parse_program(hog)
        supported_functions = set()

        if hog_type == "destination":
            supported_functions = {"fetch", "postHogCapture"}

        return create_bytecode(program, supported_functions=supported_functions, in_repl=in_repl).bytecode
    except Exception as e:
        logger.error(f"Failed to compile hog {e}", exc_info=True)
        raise serializers.ValidationError({"hog": "Hog code has errors."})
