import re
import json
import logging
from typing import Any, Optional

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers
from rest_framework.exceptions import ValidationError

from posthog.hogql import ast
from posthog.hogql.compiler.bytecode import create_bytecode
from posthog.hogql.compiler.javascript import JavaScriptCompiler
from posthog.hogql.context import HogQLContext
from posthog.hogql.parser import parse_program, parse_string_template
from posthog.hogql.visitor import TraversingVisitor

from posthog.cdp.filters import compile_filters_bytecode, compile_filters_expr
from posthog.models.integration import Integration

from products.cdp.backend.models.hog_functions.hog_function import (
    TYPES_WITH_JAVASCRIPT_SOURCE,
    TYPES_WITH_TRANSPILED_FILTERS,
)

from common.hogvm.python.stl import STL
from common.hogvm.python.stl.bytecode import BYTECODE_STL

logger = logging.getLogger(__name__)


CORE_SUPPORTED_FUNCTIONS = {"fetch", "postHogCapture"}
MAX_WORKFLOW_EMAIL_SENDERS = 10

# The mask the UI shows in place of a stored secret. A re-save that did not touch the secret
# sends this back, meaning "keep the stored value". It must never be persisted as a real secret.
MASKED_SECRET_VALUE = "********"


def masked_secret_input_keys(stored_inputs: object) -> list[str]:
    """Input keys whose stored secret is the mask rather than a real credential.

    Such an input authenticates against nothing, and the original value is gone, so only the
    owner can restore it. The match cannot be a SQL predicate: the storage column is Fernet
    encrypted, and Fernet embeds a random IV, so the same plaintext encrypts differently every
    write. Callers have to decrypt and inspect.

    A row encrypted under a key we no longer hold decrypts to the raw ciphertext string rather
    than a dict, because the field swallows the failure, so the shape is checked, not assumed.
    """
    if not isinstance(stored_inputs, dict):
        return []
    return sorted(
        key
        for key, entry in stored_inputs.items()
        if isinstance(entry, dict) and entry.get("value") == MASKED_SECRET_VALUE
    )


# Mirrors FROM_OVERRIDE_EMAIL_REGEX in nodejs/src/cdp/services/messaging/email.service.ts, which
# is what the send path enforces after rendering. Keep the two in sync.
FROM_OVERRIDE_EMAIL_REGEX = re.compile(r'^[^\s@"<>,;]+@[^\s@"<>,;]+\.[^\s@"<>,;]+$')


def _sender_integration_ids(from_value: dict) -> set[int]:
    return {
        integration_id
        for integration_id in [from_value.get("integrationId"), *(from_value.get("integrationIds") or [])]
        if isinstance(integration_id, int) and not isinstance(integration_id, bool)
    }


def _validate_email_sender_override(from_value: dict, context: dict) -> None:
    """Reject a literal custom sender address the send path would refuse.

    The runtime only sends from an address on the selected integration's verified domain; an
    off-domain override is discarded at send time with a run-log warning the author never sees.
    Catching it at save time puts the error in front of the person who can fix it. Only newly
    written sender configurations are checked: templated addresses resolve at render time, and a
    value already stored on the workflow (live or draft) is grandfathered so legacy placeholder
    data (cleaned up by a separate backfill) does not block unrelated edits.
    """
    override = (from_value.get("email") or "").strip()
    # A brace means a Liquid or Hog template that only resolves at send time.
    if not override or "{" in override:
        return

    existing = context.get("existing_email_from") or []
    # Grandfather only a fully unchanged sender configuration: the address AND the selected
    # sender set must match a stored variant. Keeping the address while switching senders must
    # re-check it against the new sender's domain, or the pair silently falls back at send time.
    for stored in existing if isinstance(existing, list) else [existing]:
        if not isinstance(stored, dict):
            continue
        if override == (stored.get("email") or "").strip() and _sender_integration_ids(
            from_value
        ) == _sender_integration_ids(stored):
            return

    get_team = context.get("get_team")
    if get_team is None:
        # No request context (internal re-saves, direct construction); the send path still
        # enforces the domain.
        return

    if not FROM_OVERRIDE_EMAIL_REGEX.match(override):
        raise serializers.ValidationError(
            {
                "input": f'The custom sender address "{override}" is not a valid email address. '
                "Use a single address like sender@yourdomain.com, or a template that resolves to one."
            }
        )

    integration_ids = _sender_integration_ids(from_value)
    if not integration_ids:
        return

    override_domain = override.split("@")[1].lower()
    # An empty cached domain means the id resolved to no email integration for this team; the
    # save is not blocked on it (there is no domain to compare), matching the uncached behavior.
    shared_cache = context.get("email_integration_domain_cache")
    domain_cache: dict[int, str] = shared_cache if isinstance(shared_cache, dict) else {}
    missing_ids = [integration_id for integration_id in integration_ids if integration_id not in domain_cache]
    if missing_ids:
        for integration in Integration.objects.filter(team_id=get_team().id, id__in=missing_ids, kind="email"):
            config = integration.config or {}
            domain_cache[integration.id] = (config.get("domain") or (config.get("email") or "").split("@")[-1]).lower()
        for integration_id in missing_ids:
            domain_cache.setdefault(integration_id, "")

    for integration_id in sorted(integration_ids):
        integration_domain = domain_cache.get(integration_id) or ""
        if integration_domain and override_domain != integration_domain:
            raise serializers.ValidationError(
                {
                    "input": f'The custom sender address "{override}" is not on the verified domain '
                    f'"{integration_domain}" of the selected sender. Use an address on that domain, '
                    "or select a different sender."
                }
            )


PRODUCT_ASYNC_FUNCTIONS: set[str] = set()


def build_html_wrap_design(html: str) -> dict:
    """Build an Unlayer design holding the given html in a single custom HTML block.

    Emails authored programmatically (API/MCP) often carry html without a design, which the
    visual editor cannot open. Wrapping the html keeps the stored html byte-identical (sends
    don't change) while giving the editor a design to load. _meta numbering mirrors what the
    Unlayer editor emits so id-addressed design operations keep working. Ids are fixed so the
    wrap is deterministic: callers that resend the same html-only value on every save would
    otherwise produce a fresh design each time, and the content-equality checks behind
    workflow revisions and hog function draft diffing would register a change on every no-op
    resave.
    """

    return {
        "counters": {"u_row": 1, "u_column": 1, "u_content_html": 1},
        "schemaVersion": 16,
        "body": {
            "id": "html-wrap-body",
            "headers": [],
            "footers": [],
            "rows": [
                {
                    "id": "html-wrap-row",
                    "cells": [1],
                    "columns": [
                        {
                            "id": "html-wrap-column",
                            "contents": [
                                {
                                    "id": "html-wrap-content",
                                    "type": "html",
                                    "values": {
                                        "html": html,
                                        "_meta": {"htmlID": "u_content_html_1", "htmlClassNames": "u_content_html"},
                                    },
                                }
                            ],
                            "values": {"_meta": {"htmlID": "u_column_1", "htmlClassNames": "u_column"}},
                        }
                    ],
                    "values": {"_meta": {"htmlID": "u_row_1", "htmlClassNames": "u_row"}},
                }
            ],
            "values": {},
        },
    }


def register_supported_function(name: str) -> None:
    PRODUCT_ASYNC_FUNCTIONS.add(name)


register_supported_function("postHogGetTicket")
register_supported_function("postHogUpdateTicket")
register_supported_function("postHogGetAccount")
register_supported_function("postHogUpdateAccount")
register_supported_function("postHogSetAccountProperties")


# Globals that the realtime transformer actually populates at runtime.
# Keep in sync with HogTransformerService.createInvocationGlobals
# (nodejs/src/cdp/hog-transformations/hog-transformer.service.ts).
TRANSFORMATION_AVAILABLE_GLOBALS = {"project", "event", "inputs"}

# Globals available to log transformations, which run per log record in the logs
# ingestion pipeline and see a log record instead of an event.
TRANSFORMATION_LOG_AVAILABLE_GLOBALS = {"project", "record", "inputs"}

# Helper functions that the transformer exposes via getTransformationFunctions
# (nodejs/src/cdp/hog-transformations/transformation-functions.ts). These resolve
# via GET_GLOBAL when referenced as a closure rather than called inline.
# postHogCapture is intentionally omitted — it lives in CORE_SUPPORTED_FUNCTIONS.
TRANSFORMATION_RUNTIME_FUNCTIONS = {
    "geoipLookup",
    "cleanNullValues",
    "isKnownBotUserAgent",
    "isKnownBotIp",
}


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


class TransformationGlobalsValidator(TraversingVisitor):
    """Reject input templates that reference globals unavailable to the realtime
    transformer (e.g. `person`, `groups`, `source`). Without this check, the bytecode
    compiles fine and the failure surfaces only at ingestion time as
    "Could not execute bytecode for input field" / "Global variable not found".
    """

    invalid_globals: set[str]

    def __init__(
        self,
        available_globals: Optional[set[str]] = None,
        runtime_functions: Optional[set[str]] = None,
    ):
        super().__init__()
        self.invalid_globals = set()
        self._available_globals = (
            available_globals if available_globals is not None else TRANSFORMATION_AVAILABLE_GLOBALS
        )
        self._runtime_functions = (
            runtime_functions if runtime_functions is not None else TRANSFORMATION_RUNTIME_FUNCTIONS
        )

    def visit_field(self, node: ast.Field):
        super().visit_field(node)
        if not node.chain:
            return
        root = str(node.chain[0])
        if (
            root in self._available_globals
            or root in self._runtime_functions
            or root in CORE_SUPPORTED_FUNCTIONS
            or root in PRODUCT_ASYNC_FUNCTIONS
            or root in STL
            or root in BYTECODE_STL
        ):
            return
        self.invalid_globals.add(root)


class DeclaredNamesCollector(TraversingVisitor):
    """Collect every identifier a hog program declares (variables, functions, params,
    loop vars, lambda args) so program-level global validation can ignore them.
    Deliberately flat rather than scope-precise: a false negative just defers the
    error to runtime, while a false positive would reject valid code.
    """

    names: set[str]

    def __init__(self):
        super().__init__()
        self.names = set()

    def visit_variable_declaration(self, node: ast.VariableDeclaration):
        self.names.add(node.name)
        super().visit_variable_declaration(node)

    def visit_function(self, node: ast.Function):
        self.names.add(node.name)
        self.names.update(node.params)
        super().visit_function(node)

    def visit_lambda(self, node: ast.Lambda):
        self.names.update(node.args)
        super().visit_lambda(node)

    def visit_for_in_statement(self, node: ast.ForInStatement):
        if node.keyVar:
            self.names.add(node.keyVar)
        self.names.add(node.valueVar)
        super().visit_for_in_statement(node)


class HyphenatedPropertyDetector(TraversingVisitor):
    errors: list[str]

    def __init__(self):
        super().__init__()
        self.errors = []

    def visit_arithmetic_operation(self, node: ast.ArithmeticOperation):
        super().visit_arithmetic_operation(node)
        if node.op == ast.ArithmeticOperationOp.Sub:
            if (
                isinstance(node.left, ast.Field)
                and len(node.left.chain) >= 2
                and isinstance(node.right, ast.Field)
                and len(node.right.chain) == 1
                and self._is_hyphenated(node.left, node.right)
            ):
                right_name = str(node.right.chain[0])
                left_last = str(node.left.chain[-1])
                parent = ".".join(str(c) for c in node.left.chain[:-1])
                self.errors.append(
                    f"Hyphens are not supported in identifiers and are interpreted as "
                    f"subtraction. Use bracket notation: "
                    f"{parent}['{left_last}-{right_name}']"
                )

    @staticmethod
    def _is_hyphenated(left: ast.Field, right: ast.Field) -> bool:
        """Check if the subtraction looks like a hyphenated property name (no spaces around the minus)."""
        if left.end is not None and right.start is not None:
            return right.start - left.end == 1
        return True


class RecordAliasRewriter(TraversingVisitor):
    """Rewrite `{record.x}` template references to `{event.properties.x}` for data-warehouse-table
    sources. The synced row is delivered under `event.properties` at runtime, so `record` is a
    friendlier alias users can write in destination/workflow templates instead of `event.properties`.
    """

    def visit_field(self, node: ast.Field):
        super().visit_field(node)
        if node.chain and str(node.chain[0]) == "record":
            node.chain = ["event", "properties", *node.chain[1:]]


def collect_inputs(node: ast.Expr) -> set[str]:
    input_collector = InputCollector()
    input_collector.visit(node)
    return input_collector.inputs


def generate_template_bytecode(
    obj: Any,
    input_collector: set[str],
    function_type: Optional[str] = None,
    is_dwh_source: bool = False,
) -> Any:
    """
    Clones an object, compiling any string values to bytecode templates
    """

    if isinstance(obj, dict):
        return {
            key: generate_template_bytecode(value, input_collector, function_type, is_dwh_source)
            for key, value in obj.items()
        }
    elif isinstance(obj, list):
        return [generate_template_bytecode(item, input_collector, function_type, is_dwh_source) for item in obj]
    elif isinstance(obj, str):
        node = parse_string_template(obj)
        if is_dwh_source:
            RecordAliasRewriter().visit(node)
        input_collector.update(collect_inputs(node))
        detector = HyphenatedPropertyDetector()
        detector.visit(node)
        if detector.errors:
            raise Exception(detector.errors[0])
        if function_type == "transformation":
            transformation_validator = TransformationGlobalsValidator()
            transformation_validator.visit(node)
            if transformation_validator.invalid_globals:
                names = ", ".join(sorted(transformation_validator.invalid_globals))
                raise Exception(
                    f"Variable not available in transformations: {names}. "
                    f"Transformations only have access to project, event, and inputs."
                )
        elif function_type == "transformation_log":
            log_validator = TransformationGlobalsValidator(
                available_globals=TRANSFORMATION_LOG_AVAILABLE_GLOBALS,
                runtime_functions=set(),
            )
            log_validator.visit(node)
            if log_validator.invalid_globals:
                names = ", ".join(sorted(log_validator.invalid_globals))
                raise Exception(
                    f"Variable not available in log transformations: {names}. "
                    f"Log transformations only have access to project, record, and inputs."
                )
        return create_bytecode(node).bytecode
    else:
        return obj


def transpile_template_code(obj: Any, compiler: JavaScriptCompiler, is_dwh_source: bool = False) -> str:
    """
    Clones an object, compiling any string values to bytecode templates
    """
    if isinstance(obj, dict):
        return (
            "{"
            + (
                ", ".join(
                    [
                        f"{json.dumps(str(key))}: {transpile_template_code(value, compiler, is_dwh_source)}"
                        for key, value in obj.items()
                    ]
                )
            )
            + "}"
        )
    elif isinstance(obj, list):
        return "[" + (", ".join([transpile_template_code(item, compiler, is_dwh_source) for item in obj])) + "]"
    elif isinstance(obj, str):
        node = parse_string_template(obj)
        if is_dwh_source:
            RecordAliasRewriter().visit(node)
        return compiler.visit(node)
    else:
        return json.dumps(obj)


def _contains_liquid_style_syntax(value: Any) -> bool:
    if isinstance(value, str):
        return "{{" in value
    if isinstance(value, dict):
        return any(_contains_liquid_style_syntax(v) for v in value.values())
    if isinstance(value, list):
        return any(_contains_liquid_style_syntax(v) for v in value)
    return False


@extend_schema_field({"oneOf": [{"type": "boolean"}, {"type": "string", "enum": ["hog", "liquid"]}]})
class _TemplatingChoiceField(serializers.ChoiceField):
    """drf-spectacular 0.29 crashes on sorted() with mixed bool/str choice keys."""

    pass


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
            "integration_multi",
            "integration_field",
            "email",
            "native_email",
            "posthog_assignee",
            "posthog_ticket_tags",
            "posthog_business_hours",
            "non_failure_status_codes",
            "customer_analytics_account_properties",
            "customer_analytics_account_relationships",
            "task_model",
            "task_repository",
            "task_mcp_installations",
        ]
    )
    key = serializers.CharField()
    label = serializers.CharField(required=False, allow_blank=True)  # type: ignore
    choices = serializers.ListField(child=serializers.DictField(), required=False)
    # For `choice` inputs: render as a searchable select on the frontend.
    searchable = serializers.BooleanField(required=False)
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
    templating = _TemplatingChoiceField(choices=[True, False, "hog", "liquid"], required=False)

    # TODO Validate choices if type=choice


@extend_schema_field({})
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
        is_dwh_source = self.context.get("is_dwh_source", False)
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
            templating_enabled = schema.get("templating", True)
            if templating_enabled:
                if not isinstance(value, bool) and not isinstance(value, str):
                    raise serializers.ValidationError({"input": f"Value must be a boolean or a template string."})
                # Liquid templating always renders to strings, which bypasses boolean type guarantees.
                # Only Hog templating is allowed for boolean fields as it preserves the actual boolean type.
                if isinstance(value, str) and attrs.get("templating") == "liquid":
                    raise serializers.ValidationError(
                        {"input": "Liquid templating is not supported for boolean fields. Use Hog templating instead."}
                    )
            else:
                if not isinstance(value, bool):
                    raise serializers.ValidationError({"input": f"Value must be a boolean."})
        elif item_type in (
            "dictionary",
            "customer_analytics_account_properties",
            "customer_analytics_account_relationships",
        ):
            if not isinstance(value, dict):
                raise serializers.ValidationError({"input": f"Value must be a dictionary."})
        elif item_type == "integration":
            if not isinstance(value, int):
                raise serializers.ValidationError({"input": f"Value must be an Integration ID."})
        elif item_type == "integration_multi":
            if not isinstance(value, list) or not all(isinstance(v, int) and not isinstance(v, bool) for v in value):
                raise serializers.ValidationError({"input": "Value must be a list of Integration IDs."})
        elif item_type == "task_repository":
            if not isinstance(value, str):
                raise serializers.ValidationError({"input": "Value must be a repository name like your-org/your-repo."})
        elif item_type == "task_model":
            # A non-empty value means a model was chosen (an empty value returned above as "use the
            # default model"), so it must name a usable model. Otherwise the run-time consumer drops
            # the setting and the task silently falls back to the default, which this guard exists to
            # prevent for programmatically authored workflows.
            model = value.get("model") if isinstance(value, dict) else None
            reasoning_effort = value.get("reasoning_effort") if isinstance(value, dict) else None
            if (
                not isinstance(value, dict)
                or not isinstance(model, str)
                or not model
                or (reasoning_effort is not None and not isinstance(reasoning_effort, str))
            ):
                raise serializers.ValidationError(
                    {
                        "input": "Value must be an object with a non-empty 'model' string and an optional 'reasoning_effort' string."
                    }
                )
        elif item_type == "task_mcp_installations":
            if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
                raise serializers.ValidationError({"input": "Value must be a list of MCP connector IDs."})
        elif item_type == "email" or item_type == "native_email":
            if not isinstance(value, dict):
                raise serializers.ValidationError({"input": f"Value must be an email object."})
            # Report every missing key in one error: these objects are typically authored
            # programmatically, and a one-at-a-time raise forces a round trip per missing key.
            missing = [f"'{key_}'" for key_ in ("from", "to", "subject") if not value.get(key_)]
            if not value.get("text") and not value.get("html"):
                missing.append("either 'text' or 'html'")
            if missing:
                label = "value" if len(missing) == 1 else "values"
                raise serializers.ValidationError({"input": f"Missing {label} for {', '.join(missing)}."})

            # Templated sender overrides on the `from` object. Non-string values would only
            # surface as a send-time failure in the runtime's schema parse, so reject them here.
            from_value = value.get("from")
            if isinstance(from_value, dict):
                wrong_types = [
                    f"'from.{key_}'"
                    for key_ in ("email", "name")
                    if from_value.get(key_) is not None and not isinstance(from_value[key_], str)
                ]
                if wrong_types:
                    label = "value" if len(wrong_types) == 1 else "values"
                    raise serializers.ValidationError(
                        {"input": f"Expected string {label} for {', '.join(wrong_types)}."}
                    )

                integration_ids = from_value.get("integrationIds")
                if integration_ids is not None:
                    if not isinstance(integration_ids, list):
                        raise serializers.ValidationError(
                            {"input": "Expected 'from.integrationIds' to be a list of Integration IDs."}
                        )
                    if len(integration_ids) > MAX_WORKFLOW_EMAIL_SENDERS:
                        raise serializers.ValidationError(
                            {"input": f"At most {MAX_WORKFLOW_EMAIL_SENDERS} email senders are allowed."}
                        )
                    if not all(
                        isinstance(integration_id, int) and not isinstance(integration_id, bool)
                        for integration_id in integration_ids
                    ):
                        raise serializers.ValidationError(
                            {"input": "Expected 'from.integrationIds' to be a list of Integration IDs."}
                        )

                _validate_email_sender_override(from_value, self.context)

            if isinstance(value.get("html"), str) and value["html"] and not value.get("design"):
                # Programmatically authored emails often supply html without a design, which the
                # visual editor can't open. Wrap it so every stored email has an editable design.
                value = {**value, "design": build_html_wrap_design(value["html"])}
                attrs["value"] = value
        elif item_type == "non_failure_status_codes":
            if not isinstance(value, list):
                raise serializers.ValidationError({"input": "Value must be a list of status codes."})
            for entry in value:
                if isinstance(entry, bool) or not isinstance(entry, int | str):
                    raise serializers.ValidationError(
                        {"input": "Entries must be integers between 400 and 599 or wildcards '4xx' or '5xx'."}
                    )
                if isinstance(entry, int):
                    if not (400 <= entry <= 599):
                        raise serializers.ValidationError({"input": "Status code numbers must be between 400 and 599."})
                else:
                    if not re.fullmatch(r"[4-5]xx", entry, re.IGNORECASE):
                        raise serializers.ValidationError({"input": "Wildcards must be '4xx' or '5xx'."})

        try:
            if value and schema.get("templating", True):
                if attrs.get("templating") == "liquid":
                    # NOTE: We don't do validaton at this level. The frontend will validate for us
                    # and we don't care about it being invalid at this stage.
                    pass
                else:
                    # If we have a value and hog templating is enabled, we need to transpile the value
                    value_is_transpiled = item_type in [
                        "string",
                        "boolean",
                        "dictionary",
                        "json",
                        "email",
                        "native_email",
                        "posthog_ticket_tags",
                        "customer_analytics_account_properties",
                        "customer_analytics_account_relationships",
                    ] or (item_type == "boolean" and isinstance(value, str))
                    if value_is_transpiled:
                        if item_type in ("email", "native_email") and isinstance(value, dict):
                            # We want to exclude the "design" property
                            value = {key: value[key] for key in value if key != "design"}

                        if function_type in TYPES_WITH_JAVASCRIPT_SOURCE:
                            compiler = JavaScriptCompiler()
                            code = transpile_template_code(value, compiler, is_dwh_source=is_dwh_source)
                            attrs["transpiled"] = {"lang": "ts", "code": code, "stl": list(compiler.stl_functions)}
                            if "bytecode" in attrs:
                                del attrs["bytecode"]
                        else:
                            input_collector: set[str] = set()
                            attrs["bytecode"] = generate_template_bytecode(
                                value, input_collector, function_type=function_type, is_dwh_source=is_dwh_source
                            )
                            attrs["input_deps"] = list(input_collector)
                            if "transpiled" in attrs:
                                del attrs["transpiled"]
        except Exception as e:
            # Liquid-style {{ ... }} in a hog-templated field is the dominant authoring mistake
            # behind transpile failures, and the compiler's own message ("Placeholders are not
            # allowed in this context") never names it - callers bisect blind without this hint.
            if _contains_liquid_style_syntax(value):
                raise serializers.ValidationError(
                    {
                        "input": (
                            "Invalid template: this field uses single-curly templating like "
                            "{person.properties.email}. Liquid-style {{ ... }} syntax is not "
                            f"supported here. ({str(e)})"
                        )
                    }
                )
            raise serializers.ValidationError({"input": f"Invalid template: {str(e)}"})

        return attrs


class InputsSerializer(serializers.DictField):
    """
    Provides the same typing as the DictField but with custom validation to only include the inputs that are in the schema
    """

    child = InputsItemSerializer()

    def run_child_validation(self, data):
        result = {}
        errors: dict[str, Any] = {}

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

            if schema.get("secret"):
                # A {"secret": true} value the user did not retype is the read-back mask, meaning
                # "keep the stored secret". The UI sends it either without a "value" key or with the
                # literal mask as the value, so both shapes must count as masked. A different "value"
                # is a rotation and must win, so it falls through to normal validation.
                is_masked = (
                    isinstance(value, dict)
                    and bool(value.get("secret"))
                    and ("value" not in value or value.get("value") == MASKED_SECRET_VALUE)
                )
                if is_masked or value == {}:
                    existing_value = (existing_secret_inputs or {}).get(key)
                    if existing_value:
                        value = existing_value
                    elif is_masked:
                        # Nothing stored to keep. Silently dropping the input here has disabled
                        # webhook auth in production - fail so the caller re-enters the value.
                        errors[key] = "No value is saved for this secret input. Enter the value again."
                        continue

            if value == {} and schema.get("required") and schema.get("default") is not None:
                # The destination editor pre-fills defaults from the template schema, but callers that
                # build inputs by hand cannot, so a required input with a default would reject them.
                value = {"value": schema["default"]}

            self.context["schema"] = schema

            # Propagate templating from schema to input item, if set
            if "templating" in schema:
                templating_val = schema["templating"]
                if isinstance(templating_val, bool):
                    if templating_val:
                        value["templating"] = "hog"
                    # If False, do not set templating field
                else:
                    value["templating"] = templating_val

            try:
                input_value = self.child.run_validation(value)

                if "value" not in input_value:
                    # Indicates no value is provided and no error was thrown which is fine so we can exclude it
                    continue

                if schema.get("secret") and input_value.get("value") == MASKED_SECRET_VALUE:
                    # The mask reached persistence, so recovery of the stored secret failed. Refuse
                    # rather than encrypt the mask and silently destroy the real credential.
                    errors[key] = "This secret input was not updated correctly. Enter the value again."
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


# Filter sources whose rows come from the warehouse rather than from events: one invocation per
# row, with the row under `event.properties` and no person attached.
DATA_WAREHOUSE_SOURCES = ("data-warehouse-table", "data-warehouse-view")


class HogFunctionFiltersSerializer(serializers.Serializer):
    source = serializers.ChoiceField(
        choices=["events", "person-updates", *DATA_WAREHOUSE_SOURCES], required=False, default="events"
    )  # type: ignore
    actions = serializers.ListField(child=serializers.DictField(), required=False)
    events = serializers.ListField(child=serializers.DictField(), required=False)
    data_warehouse = serializers.ListField(child=serializers.DictField(), required=False)
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
        function_type = self.context.get("function_type")
        team = self.context["get_team"]()

        # Ensure data is initialized as an empty dict if it's None
        data = data or {}

        if function_type == "transformation_log":
            # Filter bytecode is compiled against event-shaped globals, which log records
            # don't have — silently accepting filters would mis-evaluate at ingestion time.
            # Log transformations express conditions in Hog code instead.
            disallowed = [
                key
                for key in ("events", "actions", "properties", "data_warehouse", "filter_test_accounts")
                if data.get(key)
            ]
            if disallowed:
                raise serializers.ValidationError(
                    f"Filters are not supported for log transformations (got: {', '.join(disallowed)}). "
                    "Use conditions in the Hog code instead."
                )

        if data.get("source") == "events":
            # Don't allow events or actions for person-updates
            data.pop("data_warehouse", None)

        if data.get("source") == "person-updates":
            # Don't allow events or actions for person-updates
            data.pop("events", None)
            data.pop("actions", None)
            data.pop("data_warehouse", None)

        if data.get("source") in DATA_WAREHOUSE_SOURCES:
            # Don't allow events or actions for warehouse sources
            data.pop("events", None)
            data.pop("actions", None)

        if "data_warehouse" in data and isinstance(data["data_warehouse"], list):
            data["data_warehouse"] = [
                entry for entry in data["data_warehouse"] if entry.get("name") != "Select a table"
            ]

        # If we have a bytecode, we need to validate the transpiled
        if function_type in TYPES_WITH_TRANSPILED_FILTERS:
            compiler = JavaScriptCompiler()
            code = compiler.visit(compile_filters_expr(data, team))
            data["transpiled"] = {"lang": "ts", "code": code, "stl": list(compiler.stl_functions)}
            if "bytecode" in data:
                del data["bytecode"]
        else:
            data = compile_filters_bytecode(data, team)
            # Uncompilable filters are only fatal when the function will run (stay enabled).
            # Callers that allow saving anyway (e.g. disabling/deleting a hog function) opt out
            # via context; the error stays persisted on the filters for the UI to surface.
            if data.get("bytecode_error") and self.context.get("function_will_be_enabled", True):
                raise serializers.ValidationError(f"Invalid filter configuration: {data['bytecode_error']}")

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
    in_degree = dict.fromkeys(nodes, 0)
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


def compile_hog(
    hog: str,
    hog_type: str,
    in_repl: Optional[bool] = False,
    null_safe_comparisons: bool = False,
) -> list[Any]:
    # Attempt to compile the hog
    try:
        program = parse_program(hog)

        detector = HyphenatedPropertyDetector()
        detector.visit(program)
        if detector.errors:
            raise serializers.ValidationError({"hog": detector.errors[0]})

        supported_functions: set[str] = set()

        if hog_type == "destination":
            supported_functions = CORE_SUPPORTED_FUNCTIONS | PRODUCT_ASYNC_FUNCTIONS
        elif hog_type == "tagger":
            # Taggers classify; they must not perform side effects, so we deliberately exclude
            # CORE_SUPPORTED_FUNCTIONS (fetch, postHogCapture) and PRODUCT_ASYNC_FUNCTIONS.
            # Stated explicitly so a future refactor can't silently widen the surface.
            supported_functions = set()
        elif hog_type == "transformation_log":
            # Log transformations run synchronously per log record in the logs ingestion
            # hot path — no async functions (fetch, postHogCapture) can ever be allowed.
            # Stated explicitly so a future refactor can't silently widen the surface.
            supported_functions = set()

            # Validate the code body's globals like input templates are: without this,
            # code referencing `event`/`person` compiles fine and only fails per record
            # at ingestion time. Declared locals are excluded from the check.
            declared = DeclaredNamesCollector()
            declared.visit(program)
            body_validator = TransformationGlobalsValidator(
                available_globals=TRANSFORMATION_LOG_AVAILABLE_GLOBALS | declared.names,
                runtime_functions=set(),
            )
            body_validator.visit(program)
            if body_validator.invalid_globals:
                names = ", ".join(sorted(body_validator.invalid_globals))
                raise serializers.ValidationError(
                    {
                        "hog": f"Variable not available in log transformations: {names}. "
                        f"Log transformations only have access to project, record, and inputs."
                    }
                )

        context = HogQLContext(team_id=None)
        bytecode = create_bytecode(
            program,
            supported_functions=supported_functions,
            in_repl=in_repl,
            null_safe_comparisons=null_safe_comparisons,
            context=context,
        ).bytecode

        # The compiler only records unknown-function calls as context errors; the call still
        # compiles and fails at runtime. Log transformations run in a synchronous VM with no
        # async functions registered, so surface the error at save time instead.
        if hog_type == "transformation_log" and context.errors:
            raise serializers.ValidationError({"hog": context.errors[0].message})

        return bytecode
    except serializers.ValidationError:
        raise
    except Exception as e:
        logger.error(f"Failed to compile hog {e}", exc_info=True)
        raise serializers.ValidationError({"hog": "Hog code has errors."})
