import structlog
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import serializers, viewsets
from rest_framework.serializers import BaseSerializer

from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.hogql.bytecode import create_bytecode
from posthog.hogql.parser import parse_program
from posthog.models.hog_functions.hog_function import HogFunction
from posthog.models.hog_functions.utils import generate_template_bytecode


logger = structlog.get_logger(__name__)


class InputsSchemaItemSerializer(serializers.Serializer):
    type = serializers.ChoiceField(choices=["string", "boolean", "dictionary", "choice", "json"])
    key = serializers.CharField()
    label = serializers.CharField(required=False)
    choices = serializers.ListField(child=serializers.DictField(), required=False)
    required = serializers.BooleanField(default=False)
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
        ]
        read_only_fields = fields


class HogFunctionSerializer(HogFunctionMinimalSerializer):
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
            "bytecode",
            "inputs_schema",
            "inputs",
            "filters",
        ]
        read_only_fields = [
            "id",
            "created_at",
            "created_by",
            "updated_at",
            "bytecode",
        ]

    def validate_inputs_schema(self, value):
        if not isinstance(value, list):
            raise serializers.ValidationError("inputs_schema must be a list of objects.")

        serializer = InputsSchemaItemSerializer(data=value, many=True)

        if not serializer.is_valid():
            raise serializers.ValidationError(serializer.errors)

        return serializer.validated_data or []

    def validate(self, attrs):
        team = self.context["get_team"]()
        attrs["team"] = team
        attrs["inputs_schema"] = attrs.get("inputs_schema", [])
        attrs["inputs"] = attrs.get("inputs", {})
        attrs["filters"] = attrs.get("filters", {})

        validated_inputs = {}

        for schema in attrs["inputs_schema"]:
            value = attrs["inputs"].get(schema["key"], {})
            serializer = InputsItemSerializer(data=value, context={"schema": schema})

            if not serializer.is_valid():
                first_error = next(iter(serializer.errors.values()))[0]
                raise serializers.ValidationError({"inputs": {schema["key"]: first_error}})

            validated_inputs[schema["key"]] = serializer.validated_data

        attrs["inputs"] = validated_inputs

        # Attempt to compile the hog
        try:
            program = parse_program(attrs["hog"])
            attrs["bytecode"] = create_bytecode(program, supported_functions={"fetch"})
        except Exception as e:
            raise serializers.ValidationError({"hog": str(e)})

        return attrs

    def create(self, validated_data: dict, *args, **kwargs) -> HogFunction:
        request = self.context["request"]
        validated_data["created_by"] = request.user
        return super().create(validated_data=validated_data)


class HogFunctionViewSet(TeamAndOrgViewSetMixin, ForbidDestroyModel, viewsets.ModelViewSet):
    scope_object = "INTERNAL"  # Keep internal until we are happy to release this GA
    queryset = HogFunction.objects.all()
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["id", "team", "created_by", "enabled"]

    def get_serializer_class(self) -> type[BaseSerializer]:
        return HogFunctionMinimalSerializer if self.action == "list" else HogFunctionSerializer

    # def safely_get_queryset(self, queryset) -> QuerySet:
    #     if not self.action.endswith("update"):
    #         # Soft-deleted notebooks can be brought back with a PATCH request
    #         queryset = queryset.filter(deleted=False)

    #     queryset = queryset.select_related("created_by", "last_modified_by", "team")
    #     if self.action == "list":
    #         queryset = queryset.filter(deleted=False)
    #         queryset = self._filter_list_request(self.request, queryset)

    #     order = self.request.GET.get("order", None)
    #     if order:
    #         queryset = queryset.order_by(order)
    #     else:
    #         queryset = queryset.order_by("-last_modified_at")

    #     return queryset

    # @action(methods=["GET"], url_path="activity", detail=True, required_scopes=["activity_log:read"])
    # def activity(self, request: Request, **kwargs):
    #     notebook = self.get_object()
    #     limit = int(request.query_params.get("limit", "10"))
    #     page = int(request.query_params.get("page", "1"))

    #     activity_page = load_activity(
    #         scope="Notebook",
    #         team_id=self.team_id,
    #         item_ids=[notebook.id, notebook.short_id],
    #         limit=limit,
    #         page=page,
    #     )
    #     return activity_page_response(activity_page, limit, page, request)
