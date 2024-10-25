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

from posthog.cdp.filters import compile_filters_bytecode
from posthog.cdp.services.icons import CDPIconsService
from posthog.cdp.templates import HOG_FUNCTION_TEMPLATES_BY_ID
from posthog.cdp.validation import compile_hog, generate_template_bytecode, validate_inputs, validate_inputs_schema
from posthog.constants import AvailableFeature
from posthog.models.activity_logging.activity_log import log_activity, changes_between, Detail
from posthog.models.hog_functions.hog_function import HogFunction, HogFunctionState
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
        attrs["bytecode"] = generate_template_bytecode(attrs["hash"])

        return super().validate(attrs)


class HogFunctionSerializer(HogFunctionMinimalSerializer):
    template = HogFunctionTemplateSerializer(read_only=True)
    masking = HogFunctionMaskingSerializer(required=False, allow_null=True)

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
            "inputs_schema",
            "inputs",
            "filters",
            "masking",
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
            "template",
            "status",
        ]
        extra_kwargs = {
            "hog": {"required": False},
            "inputs_schema": {"required": False},
            "template_id": {"write_only": True},
            "deleted": {"write_only": True},
        }

    def validate(self, attrs):
        team = self.context["get_team"]()
        attrs["team"] = team

        has_addon = team.organization.is_feature_available(AvailableFeature.DATA_PIPELINES)
        instance = cast(Optional[HogFunction], self.context.get("instance", self.instance))

        if not has_addon:
            template_id = attrs.get("template_id", instance.template_id if instance else None)
            template = HOG_FUNCTION_TEMPLATES_BY_ID.get(template_id, None)

            # In this case they are only allowed to create or update the function with free templates
            if not template:
                raise serializers.ValidationError(
                    {"template_id": "The Data Pipelines addon is required to create custom functions."}
                )

            if template.status != "free":
                raise serializers.ValidationError(
                    {"template_id": "The Data Pipelines addon is required for this template."}
                )

            # Without the addon, they cannot deviate from the template
            attrs["inputs_schema"] = template.inputs_schema
            attrs["hog"] = template.hog

        if self.context.get("view") and self.context["view"].action == "create":
            # Ensure we have sensible defaults when created
            attrs["filters"] = attrs.get("filters") or {}
            attrs["inputs_schema"] = attrs.get("inputs_schema") or []
            attrs["inputs"] = attrs.get("inputs") or {}

        if "inputs_schema" in attrs:
            attrs["inputs_schema"] = validate_inputs_schema(attrs["inputs_schema"])

        if "filters" in attrs:
            attrs["filters"] = compile_filters_bytecode(attrs["filters"], team)

        if "inputs" in attrs:
            inputs = attrs["inputs"] or {}
            existing_encrypted_inputs = None

            if instance and instance.encrypted_inputs:
                existing_encrypted_inputs = instance.encrypted_inputs

            attrs["inputs_schema"] = attrs.get("inputs_schema", instance.inputs_schema if instance else [])
            attrs["inputs"] = validate_inputs(attrs["inputs_schema"], inputs, existing_encrypted_inputs)

        if "hog" in attrs:
            attrs["bytecode"] = compile_hog(attrs["hog"])

        if "type" not in attrs:
            attrs["type"] = "destination"

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
        return super().create(validated_data=validated_data)

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
        if self.action == "list":
            type = self.request.GET.get("type", "destination")
            queryset = queryset.filter(deleted=False, type=type)

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

        globals = serializer.validated_data["globals"]
        mock_async_functions = serializer.validated_data["mock_async_functions"]

        res = create_hog_invocation_test(
            team_id=hog_function.team_id,
            hog_function_id=hog_function.id,
            globals=globals,
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
