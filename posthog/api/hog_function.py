from typing import Optional, cast
import structlog
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import QuerySet

from rest_framework import serializers, viewsets
from rest_framework.serializers import BaseSerializer
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.hog_function_template import HogFunctionTemplateSerializer
from posthog.api.log_entries import LogEntryMixin
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer

from posthog.cdp.services.icons import CDPIconsService
from posthog.cdp.validation import compile_hog, validate_inputs, validate_inputs_schema
from posthog.models.hog_functions.hog_function import HogFunction, HogFunctionState
from posthog.permissions import PostHogFeatureFlagPermission
from posthog.plugins.plugin_server_api import create_hog_invocation_test


logger = structlog.get_logger(__name__)


class HogFunctionStatusSerializer(serializers.Serializer):
    state = serializers.ChoiceField(choices=[state.value for state in HogFunctionState])
    states: serializers.ListField = serializers.ListField(child=serializers.DictField())
    ratings: serializers.ListField = serializers.ListField(child=serializers.DictField())


class HogFunctionMinimalSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)

    class Meta:
        model = HogFunction
        fields = [
            "id",
            "name",
            "description",
            "created_at",
            "created_by",
            "updated_at",
            "enabled",
            "hog",
            "filters",
            "icon_url",
        ]
        read_only_fields = fields


class HogFunctionSerializer(HogFunctionMinimalSerializer):
    template = HogFunctionTemplateSerializer(read_only=True)
    status = HogFunctionStatusSerializer(read_only=True)

    class Meta:
        model = HogFunction
        fields = [
            "id",
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
            "template_id": {"write_only": True},
            "deleted": {"write_only": True},
        }

    def validate_inputs_schema(self, value):
        return validate_inputs_schema(value)

    def validate(self, attrs):
        team = self.context["get_team"]()
        attrs["team"] = team
        instance = cast(Optional[HogFunction], self.instance)

        if self.context["view"].action == "create":
            # Ensure we have sensible defaults when created
            attrs["filters"] = attrs.get("filters", {})
            attrs["inputs_schema"] = attrs.get("inputs_schema", [])
            attrs["inputs"] = attrs.get("inputs", {})

        if "inputs" in attrs:
            # If we are updating, we check all input values with secret: true and instead
            # use the existing value if set
            if instance:
                for key, val in attrs["inputs"].items():
                    if val.get("secret"):
                        attrs["inputs"][key] = instance.inputs.get(key)

                attrs["inputs_schema"] = attrs.get("inputs_schema", instance.inputs_schema)

            attrs["inputs"] = validate_inputs(attrs["inputs_schema"], attrs["inputs"])
        if "hog" in attrs:
            attrs["bytecode"] = compile_hog(attrs["hog"])

        return attrs

    def to_representation(self, data):
        data = super().to_representation(data)

        inputs_schema = data.get("inputs_schema", [])
        inputs = data.get("inputs", {})

        for schema in inputs_schema:
            if schema.get("secret") and inputs.get(schema["key"]):
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
            res.set_function_status(HogFunctionState.OVERFLOWED.value)

        return res


class HogFunctionInvocationSerializer(serializers.Serializer):
    configuration = HogFunctionSerializer(write_only=True)
    event = serializers.DictField(write_only=True)
    mock_async_functions = serializers.BooleanField(default=True, write_only=True)
    status = serializers.CharField(read_only=True)
    logs = serializers.ListField(read_only=True)


class HogFunctionViewSet(TeamAndOrgViewSetMixin, LogEntryMixin, ForbidDestroyModel, viewsets.ModelViewSet):
    scope_object = "INTERNAL"  # Keep internal until we are happy to release this GA
    queryset = HogFunction.objects.all()
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["id", "team", "created_by", "enabled"]

    permission_classes = [PostHogFeatureFlagPermission]
    posthog_feature_flag = {"hog-functions": ["create", "partial_update", "update"]}
    log_source = "hog_function"

    def get_serializer_class(self) -> type[BaseSerializer]:
        return HogFunctionMinimalSerializer if self.action == "list" else HogFunctionSerializer

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        if self.action == "list":
            queryset = queryset.filter(deleted=False)

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
        serializer = HogFunctionInvocationSerializer(data=request.data, context=self.get_serializer_context())
        if not serializer.is_valid():
            return Response(serializer.errors, status=400)

        configuration = serializer.validated_data["configuration"]
        # Remove the team from the config
        configuration.pop("team")

        event = serializer.validated_data["event"]
        mock_async_functions = serializer.validated_data["mock_async_functions"]

        res = create_hog_invocation_test(
            team_id=hog_function.team_id,
            hog_function_id=hog_function.id,
            event=event,
            configuration=configuration,
            mock_async_functions=mock_async_functions,
        )

        if res.status_code != 200:
            return Response({"status": "error"}, status=res.status_code)

        return Response(res.json())
