import json
from typing import Optional, cast

from django.db import transaction
from django.db.models import QuerySet

import structlog
from django_filters import BaseInFilter, CharFilter, FilterSet
from django_filters.rest_framework import DjangoFilterBackend
from loginas.utils import is_impersonated_session
from rest_framework import exceptions, filters, serializers, viewsets
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.serializers import BaseSerializer

from posthog.api.app_metrics2 import AppMetricsMixin
from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.hog_function_template import HogFunctionTemplateSerializer
from posthog.api.log_entries import LogEntryMixin
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.api.utils import action
from posthog.cdp.services.icons import CDPIconsService
from posthog.cdp.site_functions import get_transpiled_function
from posthog.cdp.validation import (
    HogFunctionFiltersSerializer,
    InputsSchemaItemSerializer,
    InputsSerializer,
    MappingsSerializer,
    compile_hog,
    generate_template_bytecode,
)
from posthog.exceptions_capture import capture_exception
from posthog.hogql_queries.actors_query_runner import ActorsQueryRunner
from posthog.models.activity_logging.activity_log import Change, Detail, changes_between, log_activity
from posthog.models.hog_function_template import HogFunctionTemplate
from posthog.models.hog_functions.hog_function import (
    TYPES_WITH_JAVASCRIPT_SOURCE,
    HogFunction,
    HogFunctionState,
    HogFunctionType,
)
from posthog.models.plugin import TranspilerError
from posthog.plugins.plugin_server_api import create_hog_invocation_test

# Maximum size of HOG code as a string in bytes (100KB)
MAX_HOG_CODE_SIZE_BYTES = 100 * 1024
# Maximum number of transformation functions per team
MAX_TRANSFORMATIONS_PER_TEAM = 20

logger = structlog.get_logger(__name__)


class HogFunctionStatusSerializer(serializers.Serializer):
    state = serializers.ChoiceField(choices=[state.value for state in HogFunctionState])
    tokens: serializers.IntegerField = serializers.IntegerField()


class HogFunctionMinimalSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)
    status = HogFunctionStatusSerializer(read_only=True, required=False, allow_null=True)
    template = HogFunctionTemplateSerializer(read_only=True)

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
            "execution_order",
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
    inputs_schema = serializers.ListField(child=InputsSchemaItemSerializer(required=True), required=False)
    inputs = InputsSerializer(required=False)
    mappings = serializers.ListField(child=MappingsSerializer(), required=False, allow_null=True)
    filters = HogFunctionFiltersSerializer(required=False)
    _create_in_folder = serializers.CharField(required=False, allow_blank=True, write_only=True)

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
            "execution_order",
            "_create_in_folder",
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

    # NOTE: All pre-validation should be done here such as loading the template info etc.
    def to_internal_value(self, data):
        self.initial_data = data
        team = self.context["get_team"]()
        is_create = self.context.get("is_create") or (
            self.context.get("view") and self.context["view"].action == "create"
        )
        instance = cast(Optional[HogFunction], self.context.get("instance", self.instance))

        # Override some default values from the instance that should always be set
        data["type"] = data.get("type", instance.type if instance else "destination")
        data["template_id"] = instance.template_id if instance else data.get("template_id")
        data["inputs_schema"] = data.get("inputs_schema", instance.inputs_schema if instance else [])
        data["inputs"] = data.get("inputs", instance.inputs if instance else {})

        # Always ensure filters is initialized as an empty object if it's null
        data["filters"] = data.get("filters", instance.filters if instance else {}) or {}

        # Set some context variables that are used in the sub validators
        self.context["function_type"] = data["type"]
        self.context["encrypted_inputs"] = instance.encrypted_inputs if instance else {}

        template = None
        if data["template_id"]:
            template = HogFunctionTemplate.get_template(data["template_id"])
            if not template:
                properties = {"team_id": team.id, "template_id": data.get("template_id")}
                if instance and instance.id:
                    properties["hog_function_id"] = instance.id
                capture_exception(
                    Exception(f"No template found for id '{data['template_id']}'"), additional_properties=properties
                )

                raise serializers.ValidationError({"template_id": f"No template found for id '{data['template_id']}'"})

        if is_create:
            # Set defaults for new functions
            data["inputs_schema"] = data.get("inputs_schema") or []
            data["inputs"] = data.get("inputs") or {}
            data["mappings"] = data.get("mappings") or None

            # Handle template values
            template_id = data.get("template_id")
            if template_id:
                template = HogFunctionTemplate.objects.get(template_id=data["template_id"])
                if template:
                    data["hog"] = data.get("hog") or template.code
                    data["inputs_schema"] = data.get("inputs_schema") or template.inputs_schema
                    data["inputs"] = data.get("inputs") or {}
                    data["icon_url"] = data.get("icon_url") or template.icon_url
                    data["description"] = data.get("description") or template.description
                    data["name"] = data.get("name") or template.name

        return super().to_internal_value(data)

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
        attrs["team"] = team  # NOTE: This has to be done at this level
        hog_type = self.context["function_type"]
        is_create = self.context.get("is_create") or (
            self.context.get("view") and self.context["view"].action == "create"
        )

        # Check for transformation limit per team when the function will be enabled
        # We allow unlimited creation of disabled transformations as they don't run during ingestion
        if hog_type == "transformation" and attrs.get("enabled", False):
            # Don't apply the limit for updates where the function was already enabled
            apply_limit = is_create or (isinstance(self.instance, HogFunction) and not self.instance.enabled)

            if apply_limit:
                # Count enabled and non-deleted transformations
                transformation_count = HogFunction.objects.filter(
                    team=team, type="transformation", deleted=False, enabled=True
                ).count()

                if transformation_count >= MAX_TRANSFORMATIONS_PER_TEAM:
                    raise serializers.ValidationError(
                        {
                            "type": f"Maximum of {MAX_TRANSFORMATIONS_PER_TEAM} enabled transformation functions allowed per team. Please contact support if you need this limit increased, or disable some existing transformations."
                        }
                    )

        if attrs.get("mappings", None) is not None:
            # special case for items that migrate to mappings - we want to make sure event filters are not set
            if attrs.get("filters", None) is not None:
                attrs["filters"].pop("events", None)
                attrs["filters"].pop("actions", None)

            if hog_type not in ["site_destination", "destination"]:
                raise serializers.ValidationError({"mappings": "Mappings are only allowed for destinations."})

        if "hog" in attrs:
            # First check the raw code size before trying to compile/transpile it
            hog_code_size = len(attrs["hog"].encode("utf-8"))
            if hog_code_size > MAX_HOG_CODE_SIZE_BYTES:
                raise serializers.ValidationError(
                    {
                        "hog": f"HOG code exceeds maximum size of {MAX_HOG_CODE_SIZE_BYTES // 1024}KB. Please simplify your code or contact support if you need this limit increased."
                    }
                )

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

        if is_create:
            if not attrs.get("hog"):
                raise serializers.ValidationError({"hog": "Required."})

        return attrs

    def to_representation(self, data):
        encrypted_inputs = data.encrypted_inputs or {} if isinstance(data, HogFunction) else {}
        data = super().to_representation(data)

        inputs_schema = data.get("inputs_schema", []) or []
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

        template_id = validated_data.get("template_id")
        if template_id:
            db_template = HogFunctionTemplate.objects.get(template_id=template_id)
            if not db_template:
                raise serializers.ValidationError({"template_id": f"No template found for id '{template_id}'"})
            validated_data["hog_function_template"] = db_template

        # Handle execution_order for transformation type
        if validated_data.get("type") == "transformation":
            requested_order = validated_data.get("execution_order")

            # For transformations, we need to determine the execution_order
            if requested_order is None:
                # If no order specified, add at the end
                highest_order = self._get_highest_execution_order(validated_data["team"].id)
                validated_data["execution_order"] = highest_order + 1

            # Create the function with the execution_order
            return super().create(validated_data=validated_data)
        else:
            # For non-transformation types, just create normally
            return super().create(validated_data=validated_data)

    def _get_highest_execution_order(self, team_id: int) -> int:
        """Get the highest execution_order for transformations in a team."""
        highest_order = (
            HogFunction.objects.filter(team_id=team_id, type="transformation", deleted=False)
            .order_by("-execution_order")
            .values_list("execution_order", flat=True)
            .first()
        )
        return highest_order or 0

    def update(self, instance: HogFunction, validated_data: dict, *args, **kwargs) -> HogFunction:
        # Handle undeletion or re-enabling by placing at the end when needed
        if instance.type == "transformation" and (
            (instance.deleted and validated_data.get("deleted") is False)
            or (
                not instance.enabled
                and validated_data.get("enabled") is True
                and "execution_order" not in validated_data
            )
        ):
            highest_order = self._get_highest_execution_order(instance.team_id)
            validated_data["execution_order"] = highest_order + 1

        # Standard update
        res: HogFunction = super().update(instance, validated_data)

        if res.enabled and res.status.get("state", 0) == HogFunctionState.DISABLED.value:
            res.set_function_status(HogFunctionState.DEGRADED.value)

        return res


class HogFunctionInvocationSerializer(serializers.Serializer):
    configuration = HogFunctionSerializer(write_only=True)
    globals = serializers.DictField(write_only=True, required=False)
    clickhouse_event = serializers.DictField(write_only=True, required=False)
    mock_async_functions = serializers.BooleanField(default=True, write_only=True)
    status = serializers.CharField(read_only=True)
    logs = serializers.ListField(read_only=True)
    invocation_id = serializers.CharField(required=False, allow_null=True)


class CommaSeparatedListFilter(BaseInFilter, CharFilter):
    pass


class HogFunctionFilterSet(FilterSet):
    type = CommaSeparatedListFilter(field_name="type", lookup_expr="in")

    class Meta:
        model = HogFunction
        fields = ["type", "enabled", "id", "created_by", "created_at", "updated_at"]


class HogFunctionViewSet(
    TeamAndOrgViewSetMixin,
    LogEntryMixin,
    AppMetricsMixin,
    ForbidDestroyModel,
    viewsets.ModelViewSet,
):
    scope_object = "hog_function"
    queryset = HogFunction.objects.all()
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    search_fields = ["name", "description"]
    filterset_class = HogFunctionFilterSet
    log_source = "hog_function"
    app_source = "hog_function"

    def get_serializer_class(self) -> type[BaseSerializer]:
        return HogFunctionMinimalSerializer if self.action == "list" else HogFunctionSerializer

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        if not (self.action == "partial_update" and self.request.data.get("deleted") is False):
            # We only want to include deleted functions if we are un-deleting them
            queryset = queryset.filter(deleted=False)

        if self.action == "list":
            queryset = queryset.order_by("execution_order", "-updated_at")

        final_filter_groups = []

        if self.request.GET.get("filter_groups"):
            try:
                filter_groups = json.loads(self.request.GET["filter_groups"])
                if not isinstance(filter_groups, list):
                    raise ValueError("filter_groups must be a list")

                for filter_group in filter_groups:
                    final_filter_groups.append(filter_group)

            except (ValueError, KeyError, TypeError):
                raise exceptions.ValidationError({"filter_groups": "Invalid filter_groups"})

        if self.request.GET.get("filters"):
            try:
                filters = json.loads(self.request.GET["filters"])
                final_filter_groups.append(filters)
            except (ValueError, KeyError, TypeError):
                raise exceptions.ValidationError({"filters": "Invalid filters"})

        if final_filter_groups:
            from django.db.models import Q

            combined_q = Q()

            for filter_group in final_filter_groups:
                if filter_group:
                    combined_q |= Q(filters__contains=filter_group)

            queryset = queryset.filter(combined_q)

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
        try:
            hog_function = self.get_object()
        except Exception:
            hog_function = None

        serializer = HogFunctionInvocationSerializer(
            data=request.data, context={**self.get_serializer_context(), "instance": hog_function}
        )
        if not serializer.is_valid():
            return Response(serializer.errors, status=400)

        configuration = serializer.validated_data["configuration"]
        # Remove the team from the config
        configuration.pop("team")

        res = create_hog_invocation_test(
            team_id=self.team_id,
            hog_function_id=str(hog_function.id) if hog_function else "new",
            payload=serializer.validated_data,
        )

        if res.status_code != 200:
            return Response({"status": "error"}, status=res.status_code)

        return Response(res.json())

    @action(detail=True, methods=["POST"])
    def broadcast(self, request: Request, *args, **kwargs):
        hog_function = self.get_object()

        if not hog_function.enabled:
            return Response({"error": "Cannot broadcast: function is disabled"}, status=400)

        actors_query = {
            "kind": "ActorsQuery",
            "properties": hog_function.filters.get("properties", None),
            "select": ["id", "any(pdi.distinct_id)", "properties", "created_at"],
        }

        response = ActorsQueryRunner(query=actors_query, team=self.team).calculate()

        if not hasattr(response, "results"):
            return Response({"error": "No results from actors query"}, status=400)

        for result in response.results:
            globals = {
                "event": {
                    "event": "$broadcast",
                    "elements_chain": "",
                    "distinct_id": str(result[1]),
                    "timestamp": result[3].isoformat(),
                },
                "person": {
                    "id": str(result[0]),
                    "distinct_id": str(result[1]),
                    "properties": json.loads(result[2]),
                    "created_at": result[3].isoformat(),
                },
            }
            create_hog_invocation_test(
                team_id=hog_function.team_id,
                hog_function_id=hog_function.id,
                payload={
                    "globals": globals,
                    "configuration": HogFunctionSerializer(hog_function).data,
                    "mock_async_functions": False,
                },
            )

        return Response({"success": True})

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

    @action(methods=["PATCH"], detail=False)
    def rearrange(self, request: Request, *args, **kwargs) -> Response:
        """Update the execution order of multiple HogFunctions."""
        team = self.team
        orders: dict[str, int] = request.data.get("orders", {})

        if not orders:
            raise exceptions.ValidationError("No orders provided")

        with transaction.atomic():
            # Get all functions in a single query and validate them
            function_ids = list(orders.keys())
            functions = {
                str(f.id): f
                for f in HogFunction.objects.filter(
                    id__in=function_ids, team=team, type="transformation", deleted=False
                )
            }

            # Validate all functions exist
            missing_ids = set(function_ids) - set(functions.keys())
            if missing_ids:
                raise exceptions.ValidationError(f"HogFunction with id {missing_ids.pop()} does not exist")

            # Update orders and create activity logs
            from django.contrib.auth.models import AnonymousUser
            from django.utils import timezone

            current_time = timezone.now()
            user = None if isinstance(request.user, AnonymousUser) else request.user

            for function_id, function in functions.items():
                new_order = orders[function_id]
                old_order = function.execution_order

                if old_order != new_order:
                    function.execution_order = new_order
                    function.updated_at = current_time

                    log_activity(
                        organization_id=self.organization.id,
                        team_id=self.team_id,
                        user=user,
                        item_id=str(function.id),
                        was_impersonated=is_impersonated_session(request),
                        scope="HogFunction",
                        activity="updated",
                        detail=Detail(
                            name=function.name,
                            type="transformation",
                            changes=[
                                Change(
                                    type="HogFunction",
                                    action="changed",
                                    field="priority",
                                    before=str(old_order),
                                    after=str(new_order),
                                )
                            ],
                        ),
                    )

                    function.save(update_fields=["execution_order", "updated_at"])

        # Get final ordered list in a single query
        transformations = HogFunction.objects.filter(team=team, type="transformation", deleted=False).order_by(
            "execution_order"
        )

        serializer = self.get_serializer(transformations, many=True)
        return Response(serializer.data)
