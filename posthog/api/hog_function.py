import json
from typing import Optional, cast
import structlog
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import QuerySet
from loginas.utils import is_impersonated_session

from rest_framework import serializers, viewsets, exceptions
from rest_framework.serializers import BaseSerializer
from posthog.api.utils import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.app_metrics2 import AppMetricsMixin
from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.hog_function_template import HogFunctionTemplateSerializer
from posthog.api.log_entries import LogEntryMixin
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer

from posthog.cdp.filters import compile_filters_bytecode, compile_filters_expr
from posthog.cdp.services.icons import CDPIconsService
from posthog.cdp.templates import HOG_FUNCTION_TEMPLATES_BY_ID
from posthog.cdp.validation import compile_hog, generate_template_bytecode, validate_inputs, validate_inputs_schema
from posthog.cdp.site_functions import get_transpiled_function
from posthog.constants import AvailableFeature
from posthog.hogql.compiler.javascript import JavaScriptCompiler
from posthog.models.activity_logging.activity_log import log_activity, changes_between, Detail
from posthog.models.hog_functions.hog_function import (
    HogFunction,
    HogFunctionState,
    TYPES_WITH_COMPILED_FILTERS,
    TYPES_WITH_TRANSPILED_FILTERS,
    TYPES_WITH_JAVASCRIPT_SOURCE,
    HogFunctionType,
)
from posthog.models.plugin import TranspilerError
from posthog.plugins.plugin_server_api import create_hog_invocation_test


logger = structlog.get_logger(__name__)


class HogFunctionStatusSerializer(serializers.Serializer):
    state = serializers.ChoiceField(choices=[state.value for state in HogFunctionState])
    rating: serializers.FloatField = serializers.FloatField()
    tokens: serializers.IntegerField = serializers.IntegerField()


class HogFunctionMinimalSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)
    status = HogFunctionStatusSerializer(read_only=True, required=False, allow_null=True)

    class Meta:
        model = HogFunction
        fields = [
            "id",
            "type",
            "name",
            "description",
            "created_at",
            "created_by",
            "updated_at",
            "enabled",
            "hog",
            "filters",
            "icon_url",
            "template",
            "status",
        ]
        read_only_fields = fields


class HogFunctionMaskingSerializer(serializers.Serializer):
    ttl = serializers.IntegerField(
        required=True, min_value=60, max_value=60 * 60 * 24
    )  # NOTE: 24 hours max for now - we might increase this later
    threshold = serializers.IntegerField(required=False, allow_null=True)
    hash = serializers.CharField(required=True)
    bytecode = serializers.JSONField(required=False, allow_null=True)

    def validate(self, attrs):
        attrs["bytecode"] = generate_template_bytecode(attrs["hash"], input_collector=set())

        return super().validate(attrs)


class HogFunctionSerializer(HogFunctionMinimalSerializer):
    template = HogFunctionTemplateSerializer(read_only=True)
    masking = HogFunctionMaskingSerializer(required=False, allow_null=True)

    type = serializers.ChoiceField(choices=HogFunctionType.choices, required=False, allow_null=True)

    class Meta:
        model = HogFunction
        fields = [
            "id",
            "type",
            "name",
            "description",
            "created_at",
            "created_by",
            "updated_at",
            "enabled",
            "deleted",
            "hog",
            "bytecode",
            "transpiled",
            "inputs_schema",
            "inputs",
            "filters",
            "masking",
            "mappings",
            "icon_url",
            "template",
            "template_id",
            "status",
        ]
        read_only_fields = [
            "id",
            "created_at",
            "created_by",
            "updated_at",
            "bytecode",
            "transpiled",
            "template",
            "status",
        ]
        extra_kwargs = {
            "hog": {"required": False},
            "inputs_schema": {"required": False},
            "template_id": {"write_only": True},
            "deleted": {"write_only": True},
            "type": {"required": True},
        }

    def validate_type(self, value):
        # Ensure it is only set when creating a new function
        if self.context.get("view") and self.context["view"].action == "create":
            return value

        instance = cast(Optional[HogFunction], self.context.get("instance", self.instance))
        if instance and instance.type != value:
            raise serializers.ValidationError("Cannot modify the type of an existing function")
        return value

    def validate(self, attrs):
        team = self.context["get_team"]()
        attrs["team"] = team

        has_addon = team.organization.is_feature_available(AvailableFeature.DATA_PIPELINES)
        instance = cast(Optional[HogFunction], self.context.get("instance", self.instance))

        hog_type = attrs.get("type", instance.type if instance else "destination")
        is_create = self.context.get("view") and self.context["view"].action == "create"

        template_id = attrs.get("template_id", instance.template_id if instance else None)
        template = HOG_FUNCTION_TEMPLATES_BY_ID.get(template_id, None)

        if not has_addon:
            # In this case they are only allowed to create or update the function with free templates
            if not template:
                raise serializers.ValidationError(
                    {"template_id": "The Data Pipelines addon is required to create custom functions."}
                )

            if template.status != "free" and not instance:
                raise serializers.ValidationError(
                    {"template_id": "The Data Pipelines addon is required for this template."}
                )

            # Without the addon you can't deviate from the template
            attrs["hog"] = template.hog
            attrs["inputs_schema"] = template.inputs_schema

        if is_create:
            # Ensure we have sensible defaults when created
            attrs["filters"] = attrs.get("filters") or {}
            attrs["inputs_schema"] = attrs.get("inputs_schema") or []
            attrs["inputs"] = attrs.get("inputs") or {}
            attrs["mappings"] = attrs.get("mappings") or None

            # And if there is a template, use the template values if not overridden
            if template:
                attrs["hog"] = attrs.get("hog") or template.hog
                attrs["inputs_schema"] = attrs.get("inputs_schema") or template.inputs_schema
                attrs["inputs"] = attrs.get("inputs") or {}

        # Used for both top level input validation, and mappings input validation
        def validate_input_and_filters(attrs: dict):
            if "inputs_schema" in attrs:
                attrs["inputs_schema"] = validate_inputs_schema(attrs["inputs_schema"])

            if "inputs" in attrs:
                inputs = attrs["inputs"] or {}
                existing_encrypted_inputs = None

                if instance and instance.encrypted_inputs:
                    existing_encrypted_inputs = instance.encrypted_inputs

                attrs["inputs_schema"] = attrs.get("inputs_schema", instance.inputs_schema if instance else [])
                attrs["inputs"] = validate_inputs(attrs["inputs_schema"], inputs, existing_encrypted_inputs, hog_type)

            if "filters" in attrs:
                if hog_type in TYPES_WITH_COMPILED_FILTERS:
                    attrs["filters"] = compile_filters_bytecode(attrs["filters"], team)
                elif hog_type in TYPES_WITH_TRANSPILED_FILTERS:
                    compiler = JavaScriptCompiler()
                    code = compiler.visit(compile_filters_expr(attrs["filters"], team))
                    attrs["filters"]["transpiled"] = {"lang": "ts", "code": code, "stl": list(compiler.stl_functions)}
                    if "bytecode" in attrs["filters"]:
                        del attrs["filters"]["bytecode"]

        validate_input_and_filters(attrs)

        if attrs.get("mappings", None) is not None:
            if hog_type not in ["site_destination", "destination"]:
                raise serializers.ValidationError({"mappings": "Mappings are only allowed for destinations."})
            for mapping in attrs["mappings"]:
                validate_input_and_filters(mapping)

        if "hog" in attrs:
            if hog_type in TYPES_WITH_JAVASCRIPT_SOURCE:
                try:
                    # Validate transpilation using the model instance
                    attrs["transpiled"] = get_transpiled_function(
                        HogFunction(
                            team=team,
                            hog=attrs["hog"],
                            filters=attrs["filters"],
                            inputs=attrs["inputs"],
                        )
                    )
                except TranspilerError:
                    raise serializers.ValidationError({"hog": "Error in TypeScript code"})
                attrs["bytecode"] = None
            else:
                attrs["bytecode"] = compile_hog(attrs["hog"], hog_type)
                attrs["transpiled"] = None
        else:
            attrs["bytecode"] = None
            attrs["transpiled"] = None

        if is_create:
            if not attrs.get("hog"):
                raise serializers.ValidationError({"hog": "Required."})

        return super().validate(attrs)

    def to_representation(self, data):
        encrypted_inputs = data.encrypted_inputs or {} if isinstance(data, HogFunction) else {}
        data = super().to_representation(data)

        inputs_schema = data.get("inputs_schema", [])
        inputs = data.get("inputs") or {}

        for schema in inputs_schema:
            if schema.get("secret"):
                # TRICKY: We used to store these inputs so we check both the encrypted and non-encrypted inputs
                has_value = encrypted_inputs.get(schema["key"]) or inputs.get(schema["key"])
                if has_value:
                    # Marker to indicate to the user that a secret is set
                    inputs[schema["key"]] = {"secret": True}

        data["inputs"] = inputs

        return data

    def create(self, validated_data: dict, *args, **kwargs) -> HogFunction:
        request = self.context["request"]
        validated_data["created_by"] = request.user
        hog_function = super().create(validated_data=validated_data)

        return hog_function

    def update(self, instance: HogFunction, validated_data: dict, *args, **kwargs) -> HogFunction:
        res: HogFunction = super().update(instance, validated_data)

        if res.enabled and res.status.get("state", 0) >= HogFunctionState.DISABLED_TEMPORARILY.value:
            res.set_function_status(HogFunctionState.DEGRADED.value)

        return res


class HogFunctionInvocationSerializer(serializers.Serializer):
    configuration = HogFunctionSerializer(write_only=True)
    globals = serializers.DictField(write_only=True)
    mock_async_functions = serializers.BooleanField(default=True, write_only=True)
    status = serializers.CharField(read_only=True)
    logs = serializers.ListField(read_only=True)


class HogFunctionViewSet(
    TeamAndOrgViewSetMixin, LogEntryMixin, AppMetricsMixin, ForbidDestroyModel, viewsets.ModelViewSet
):
    scope_object = "INTERNAL"  # Keep internal until we are happy to release this GA
    queryset = HogFunction.objects.all()
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["id", "team", "created_by", "enabled"]

    log_source = "hog_function"
    app_source = "hog_function"

    def get_serializer_class(self) -> type[BaseSerializer]:
        return HogFunctionMinimalSerializer if self.action == "list" else HogFunctionSerializer

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        if not (self.action == "partial_update" and self.request.data.get("deleted") is False):
            # We only want to include deleted functions if we are un-deleting them
            queryset = queryset.filter(deleted=False)

        if self.action == "list":
            if "type" in self.request.GET:
                types = [self.request.GET.get("type", "destination")]
            elif "types" in self.request.GET:
                types = self.request.GET.get("types", "destination").split(",")
            else:
                types = ["destination"]
            queryset = queryset.filter(type__in=types)

        if self.request.GET.get("filters"):
            try:
                filters = json.loads(self.request.GET["filters"])
                if "actions" in filters:
                    action_ids = [str(action.get("id")) for action in filters.get("actions", []) if action.get("id")]
                    del filters["actions"]
                    query = """
                        EXISTS (
                            SELECT 1
                            FROM jsonb_array_elements(filters->'actions') AS elem
                            WHERE elem->>'id' = ANY(%s)
                        )
                    """
                    queryset = queryset.extra(where=[query], params=[action_ids])

                if filters:
                    queryset = queryset.filter(filters__contains=filters)
            except (ValueError, KeyError, TypeError):
                raise exceptions.ValidationError({"filter": f"Invalid filter"})

        return queryset

    @action(detail=False, methods=["GET"])
    def icons(self, request: Request, *args, **kwargs):
        query = request.GET.get("query")
        if not query:
            return Response([])

        icons = CDPIconsService().list_icons(query, icon_url_base="/api/projects/@current/hog_functions/icon/?id=")

        return Response(icons)

    @action(detail=False, methods=["GET"])
    def icon(self, request: Request, *args, **kwargs):
        id = request.GET.get("id")
        if not id:
            raise serializers.ValidationError("id is required")

        icon_service = CDPIconsService()

        return icon_service.get_icon_http_response(id)

    @action(detail=True, methods=["POST"])
    def invocations(self, request: Request, *args, **kwargs):
        hog_function = self.get_object()
        serializer = HogFunctionInvocationSerializer(
            data=request.data, context={**self.get_serializer_context(), "instance": hog_function}
        )
        if not serializer.is_valid():
            return Response(serializer.errors, status=400)

        configuration = serializer.validated_data["configuration"]
        # Remove the team from the config
        configuration.pop("team")

        hog_globals = serializer.validated_data["globals"]
        mock_async_functions = serializer.validated_data["mock_async_functions"]

        res = create_hog_invocation_test(
            team_id=hog_function.team_id,
            hog_function_id=hog_function.id,
            globals=hog_globals,
            configuration=configuration,
            mock_async_functions=mock_async_functions,
        )

        if res.status_code != 200:
            return Response({"status": "error"}, status=res.status_code)

        return Response(res.json())

    def perform_create(self, serializer):
        serializer.save()
        log_activity(
            organization_id=self.organization.id,
            team_id=self.team_id,
            user=serializer.context["request"].user,
            was_impersonated=is_impersonated_session(serializer.context["request"]),
            item_id=serializer.instance.id,
            scope="HogFunction",
            activity="created",
            detail=Detail(name=serializer.instance.name, type=serializer.instance.type or "destination"),
        )

    def perform_update(self, serializer):
        instance_id = serializer.instance.id

        try:
            before_update = HogFunction.objects.get(pk=instance_id)
        except HogFunction.DoesNotExist:
            before_update = None

        serializer.save()

        changes = changes_between("HogFunction", previous=before_update, current=serializer.instance)

        log_activity(
            organization_id=self.organization.id,
            team_id=self.team_id,
            user=serializer.context["request"].user,
            was_impersonated=is_impersonated_session(serializer.context["request"]),
            item_id=instance_id,
            scope="HogFunction",
            activity="updated",
            detail=Detail(
                changes=changes, name=serializer.instance.name, type=serializer.instance.type or "destination"
            ),
        )
