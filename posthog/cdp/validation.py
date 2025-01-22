import json
import logging
from typing import Any, Optional
from rest_framework import serializers

from posthog.hogql.compiler.bytecode import create_bytecode
from posthog.hogql.compiler.javascript import JavaScriptCompiler
from posthog.hogql.parser import parse_program, parse_string_template
from posthog.hogql.visitor import TraversingVisitor
from posthog.models.hog_functions.hog_function import TYPES_WITH_JAVASCRIPT_SOURCE
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
        choices=["string", "boolean", "dictionary", "choice", "json", "integration", "integration_field", "email"]
    )
    key = serializers.CharField()
    label = serializers.CharField(required=False, allow_blank=True)  # type: ignore
    choices = serializers.ListField(child=serializers.DictField(), required=False)
    required = serializers.BooleanField(default=False)  # type: ignore
    default = serializers.JSONField(required=False)
    secret = serializers.BooleanField(default=False)
    description = serializers.CharField(required=False)
    integration = serializers.CharField(required=False)
    integration_key = serializers.CharField(required=False)
    requires_field = serializers.CharField(required=False)
    integration_field = serializers.CharField(required=False)
    requiredScopes = serializers.CharField(required=False)

    # TODO Validate choices if type=choice


class AnyInputField(serializers.Field):
    def to_internal_value(self, data):
        return data

    def to_representation(self, value):
        return value


class InputsItemSerializer(serializers.Serializer):
    value = AnyInputField(required=False)
    bytecode = serializers.ListField(required=False, read_only=True)
    # input_deps = serializers.ListField(required=False)
    order = serializers.IntegerField(required=False)
    transpiled = serializers.JSONField(required=False)

    def validate(self, attrs):
        schema = self.context["schema"]
        function_type = self.context["function_type"]
        value = attrs.get("value")

        name: str = schema["key"]
        item_type = schema["type"]

        if schema.get("required") and (value is None or value == ""):
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
        elif item_type == "integration":
            if not isinstance(value, int):
                raise serializers.ValidationError({"inputs": {name: f"Value must be an Integration ID."}})
        elif item_type == "email":
            if not isinstance(value, dict):
                raise serializers.ValidationError({"inputs": {name: f"Value must be an Integration ID."}})
            for key_ in ["from", "to", "subject"]:
                if not value.get(key_):
                    raise serializers.ValidationError({"inputs": {name: f"Missing value for '{key_}'."}})

            if not value.get("text") and not value.get("html"):
                raise serializers.ValidationError({"inputs": {name: f"Either 'text' or 'html' is required."}})

        try:
            if value:
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
            raise serializers.ValidationError({"inputs": {name: f"Invalid template: {str(e)}"}})

        return attrs


def validate_inputs_schema(value: list) -> list:
    if not isinstance(value, list):
        raise serializers.ValidationError("inputs_schema must be a list of objects.")

    serializer = InputsSchemaItemSerializer(data=value, many=True)

    if not serializer.is_valid():
        raise serializers.ValidationError(serializer.errors)

    return serializer.validated_data or []


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


def validate_inputs(
    inputs_schema: list,
    inputs: dict,
    existing_secret_inputs: Optional[dict] = None,
    function_type: Optional[str] = None,
) -> dict:
    """
    Tricky: We want to allow overriding the secret inputs, but not return them.
    If we have a given input then we use it, otherwise we pull it from the existing secrets.
    Then we do topological sorting based on input_deps to assign order.
    """

    validated_inputs = {}

    # Validate each input against the schema
    for schema in inputs_schema:
        value = inputs.get(schema["key"]) or {}

        # We only load the existing secret if the schema is secret and the given value has "secret" set
        if schema.get("secret") and existing_secret_inputs and value and value.get("secret"):
            value = existing_secret_inputs.get(schema["key"]) or {}

        serializer = InputsItemSerializer(
            data=value, context={"schema": schema, "function_type": function_type or "destination"}
        )

        if not serializer.is_valid():
            raise serializers.ValidationError(serializer.errors)

        validated_data = serializer.validated_data

        # If it's a secret input, not required, and no value was provided, don't add it
        if schema.get("secret", False) and not schema.get("required", False) and "value" not in validated_data:
            # Skip adding this input entirely
            continue

        validated_inputs[schema["key"]] = validated_data

    # We'll topologically sort keys based on their input_deps.
    edges = {}
    all_keys = list(validated_inputs.keys())
    for k, v in validated_inputs.items():
        deps = v.get("input_deps", [])
        deps = [d for d in deps if d in validated_inputs]
        edges[k] = deps

    sorted_keys = topological_sort(all_keys, edges)

    # Assign order according to topological sort
    for i, key in enumerate(sorted_keys):
        validated_inputs[key]["order"] = i
        if "input_deps" in validated_inputs[key]:
            del validated_inputs[key]["input_deps"]

    # Rebuild in sorted order
    sorted_validated_inputs = {key: validated_inputs[key] for key in sorted_keys}

    return sorted_validated_inputs


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
