import structlog
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import serializers, viewsets, mixins
from rest_framework.serializers import BaseSerializer
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.hogql.bytecode import create_bytecode
from posthog.hogql.parser import parse_program
from posthog.models.hog_functions.hog_function import HogFunction
from posthog.models.hog_functions.hog_function_template import HogFunctionTemplate
from posthog.models.hog_functions.templates import HOG_FUNCTION_TEMPLATES
from posthog.permissions import PostHogFeatureFlagPermission
from rest_framework_dataclasses.serializers import DataclassSerializer


logger = structlog.get_logger(__name__)


class HogFunctionTemplateSerializer(DataclassSerializer):
    class Meta:
        dataclass = HogFunctionTemplate

    # def validate_inputs_schema(self, value):
    #     if not isinstance(value, list):
    #         raise serializers.ValidationError("inputs_schema must be a list of objects.")

    #     serializer = InputsSchemaItemSerializer(data=value, many=True)

    #     if not serializer.is_valid():
    #         raise serializers.ValidationError(serializer.errors)

    #     return serializer.validated_data or []

    # def validate(self, attrs):
    #     team = self.context["get_team"]()
    #     attrs["team"] = team
    #     attrs["inputs_schema"] = attrs.get("inputs_schema", [])
    #     attrs["inputs"] = attrs.get("inputs", {})
    #     attrs["filters"] = attrs.get("filters", {})

    #     validated_inputs = {}

    #     for schema in attrs["inputs_schema"]:
    #         value = attrs["inputs"].get(schema["key"], {})
    #         serializer = InputsItemSerializer(data=value, context={"schema": schema})

    #         if not serializer.is_valid():
    #             first_error = next(iter(serializer.errors.values()))[0]
    #             raise serializers.ValidationError({"inputs": {schema["key"]: first_error}})

    #         validated_inputs[schema["key"]] = serializer.validated_data

    #     attrs["inputs"] = validated_inputs

    #     # Attempt to compile the hog
    #     try:
    #         program = parse_program(attrs["hog"])
    #         attrs["bytecode"] = create_bytecode(program, supported_functions={"fetch"})
    #     except Exception as e:
    #         raise serializers.ValidationError({"hog": str(e)})

    #     return attrs

    # def create(self, validated_data: dict, *args, **kwargs) -> HogFunction:
    #     request = self.context["request"]
    #     validated_data["created_by"] = request.user
    #     return super().create(validated_data=validated_data)


class HogFunctionTemplateViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "INTERNAL"  # Keep internal until we are happy to release this GA
    queryset = HogFunction.objects.none()
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["id", "team", "created_by", "enabled"]

    permission_classes = [PostHogFeatureFlagPermission]
    posthog_feature_flag = {"hog-functions": ["create", "partial_update", "update"]}

    serializer_class = HogFunctionTemplateSerializer

    def list(self, request: Request, *args, **kwargs):
        # TODO: Filtering for status?

        serializer = HogFunctionTemplateSerializer(HOG_FUNCTION_TEMPLATES, many=True)
        return Response(serializer.data)
