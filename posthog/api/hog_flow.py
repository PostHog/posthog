import json
from typing import Optional, cast

from django.db.models import QuerySet

import structlog
import posthoganalytics
from django_filters import BaseInFilter, CharFilter, FilterSet
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema_view
from rest_framework import exceptions, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.serializers import BaseSerializer

from posthog.api.app_metrics2 import AppMetricsMixin
from posthog.api.documentation import extend_schema, extend_schema_field
from posthog.api.hog_flow_batch_job import HogFlowBatchJobSerializer
from posthog.api.log_entries import LogEntryMixin
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.api.utils import log_activity_from_viewset
from posthog.auth import InternalAPIAuthentication
from posthog.cdp.validation import (
    HogFunctionFiltersSerializer,
    InputsSchemaItemSerializer,
    InputsSerializer,
    generate_template_bytecode,
)
from posthog.models import Team
from posthog.models.feature_flag.user_blast_radius import (
    PERSON_BATCH_SIZE,
    get_user_blast_radius,
    get_user_blast_radius_persons,
)
from posthog.models.hog_flow.hog_flow import BILLABLE_ACTION_TYPES, HogFlow
from posthog.models.hog_function_template import HogFunctionTemplate
from posthog.plugins.plugin_server_api import create_hog_flow_invocation_test

from products.workflows.backend.models.hog_flow_batch_job import HogFlowBatchJob

logger = structlog.get_logger(__name__)

_HOG_FLOW_EDGE_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "from": {"type": "string", "description": "ID of the source action node."},
        "to": {"type": "string", "description": "ID of the target action node."},
        "type": {"type": "string", "enum": ["continue", "branch"], "description": "Edge type."},
        "index": {
            "type": "integer",
            "nullable": True,
            "description": "Branch index (0-based) for ordered branching across multiple outgoing edges.",
        },
    },
    "required": ["from", "to", "type"],
}

_HOG_FLOW_VARIABLE_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "key": {"type": "string", "description": "Variable name. Referenced in action configs as {variables.key}."},
        "value": {"type": "string", "default": "", "description": "Default value for this variable."},
    },
    "required": ["key"],
}

_HOG_FLOW_CONVERSION_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "window_minutes": {
            "type": "integer",
            "nullable": True,
            "description": "Time window in minutes within which a conversion is counted. Null means no limit.",
        },
        "filters": {
            "type": "array",
            "items": {"type": "object", "additionalProperties": True},
            "nullable": True,
            "description": "Array of PostHog property filter objects that define the conversion event.",
        },
        "bytecode": {
            "type": "array",
            "items": {},
            "nullable": True,
            "description": "Compiled bytecode for the conversion filter. Auto-generated; do not set manually.",
        },
    },
}

_HOG_FLOW_OUTPUT_VARIABLE_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "key": {"type": "string", "description": "Variable name to store the action output in."},
        "result_path": {
            "type": "string",
            "nullable": True,
            "description": "JSONPath expression into the action result to extract a specific value.",
        },
        "spread": {
            "type": "boolean",
            "nullable": True,
            "description": "When true, spreads all result keys as separate top-level variables.",
        },
    },
    "required": ["key"],
}
_HOG_FLOW_ACTION_CONFIG_SCHEMA: dict = {
    "description": "Action-specific configuration. Structure is determined by the action type.",
    "oneOf": [
        {
            "title": "Event trigger",
            "type": "object",
            "properties": {
                "type": {"type": "string", "enum": ["event"]},
                "filters": {
                    "type": "object",
                    "additionalProperties": True,
                    "description": "PostHog event and property filters.",
                },
                "filter_test_accounts": {"type": "boolean"},
            },
            "required": ["type"],
        },
        {
            "title": "Function-backed trigger (webhook / manual / schedule / tracking_pixel)",
            "type": "object",
            "properties": {
                "type": {"type": "string", "enum": ["webhook", "manual", "schedule", "tracking_pixel"]},
                "template_id": {"type": "string", "description": "HogFunction template ID."},
                "inputs": {
                    "type": "object",
                    "additionalProperties": True,
                    "description": "Input values keyed by schema item name.",
                },
                "scheduled_at": {"type": "string", "description": "ISO 8601 datetime for one-time scheduling."},
            },
            "required": ["type", "template_id"],
        },
        {
            "title": "Batch trigger",
            "type": "object",
            "properties": {
                "type": {"type": "string", "enum": ["batch"]},
                "filters": {
                    "type": "object",
                    "additionalProperties": True,
                    "description": "PostHog property filters selecting persons to process.",
                },
            },
            "required": ["type", "filters"],
        },
        {
            "title": "Delay",
            "type": "object",
            "properties": {
                "type": {"type": "string", "enum": ["delay"]},
                "delay_duration": {"type": "string", "description": "ISO 8601 duration string, e.g. 'PT1H'."},
            },
            "required": ["type", "delay_duration"],
        },
        {
            "title": "Wait until condition",
            "type": "object",
            "properties": {
                "type": {"type": "string", "enum": ["wait_until_condition"]},
                "condition": {
                    "type": "object",
                    "additionalProperties": True,
                    "description": "Single condition with a filters object.",
                },
                "max_wait_duration": {"type": "string", "description": "ISO 8601 maximum wait duration."},
            },
            "required": ["type", "condition", "max_wait_duration"],
        },
        {
            "title": "Conditional branch",
            "type": "object",
            "properties": {
                "type": {"type": "string", "enum": ["conditional_branch"]},
                "conditions": {
                    "type": "array",
                    "items": {"type": "object", "additionalProperties": True},
                    "description": "Ordered list of conditions with filters objects.",
                },
            },
            "required": ["type", "conditions"],
        },
        {
            "title": "Random cohort branch",
            "type": "object",
            "properties": {
                "type": {"type": "string", "enum": ["random_cohort_branch"]},
                "cohorts": {
                    "type": "array",
                    "items": {"type": "object", "additionalProperties": True},
                    "description": "Cohort percentage splits, each with a percentage and optional name.",
                },
            },
            "required": ["type", "cohorts"],
        },
        {
            "title": "CDP function",
            "type": "object",
            "properties": {
                "type": {
                    "type": "string",
                    "enum": ["function", "function_email", "function_sms", "function_push"],
                },
                "template_id": {
                    "type": "string",
                    "description": "HogFunction template ID. Use the hog_function_templates endpoints to discover available templates.",
                },
                "inputs": {
                    "type": "object",
                    "additionalProperties": True,
                    "description": "Input values keyed by schema item name.",
                },
            },
            "required": ["type", "template_id"],
        },
        {
            "title": "Exit",
            "type": "object",
            "properties": {
                "type": {"type": "string", "enum": ["exit"]},
                "reason": {"type": "string", "description": "Human-readable exit reason."},
            },
            "required": ["type"],
        },
    ],
}


@extend_schema_field(_HOG_FLOW_ACTION_CONFIG_SCHEMA)
class HogFlowActionConfigField(serializers.JSONField):
    pass


@extend_schema_field(_HOG_FLOW_OUTPUT_VARIABLE_SCHEMA)
class HogFlowOutputVariableField(serializers.JSONField):
    pass


@extend_schema_field({"type": "array", "items": _HOG_FLOW_EDGE_SCHEMA})
class HogFlowEdgesField(serializers.JSONField):
    pass


@extend_schema_field(_HOG_FLOW_CONVERSION_SCHEMA)
class HogFlowConversionField(serializers.JSONField):
    pass


@extend_schema_field({"type": "array", "items": _HOG_FLOW_VARIABLE_SCHEMA})
class HogFlowVariablesField(serializers.JSONField):
    pass


class HogFlowConfigFunctionInputsSerializer(serializers.Serializer):
    inputs_schema = serializers.ListField(child=InputsSchemaItemSerializer(), required=False)
    inputs = InputsSerializer(required=False)

    def to_internal_value(self, data):
        # Weirdly nested serializers don't get this set...
        self.initial_data = data
        return super().to_internal_value(data)


class HogFlowActionSerializer(serializers.Serializer):
    id = serializers.CharField()
    name = serializers.CharField(max_length=400)
    description = serializers.CharField(allow_blank=True, default="")
    on_error = serializers.ChoiceField(
        choices=["continue", "abort", "complete", "branch"], required=False, allow_null=True
    )
    created_at = serializers.IntegerField(
        help_text="Unix epoch timestamp (milliseconds) when this action was first added to the workflow.",
    )
    updated_at = serializers.IntegerField(
        help_text="Unix epoch timestamp (milliseconds) when this action was last modified.",
    )
    filters = HogFunctionFiltersSerializer(required=False, default=None, allow_null=True)
    type = serializers.CharField(max_length=100)
    config = HogFlowActionConfigField()
    output_variable = HogFlowOutputVariableField(required=False, allow_null=True)

    def to_internal_value(self, data):
        # Weirdly nested serializers don't get this set...
        self.initial_data = data
        return super().to_internal_value(data)

    def validate(self, data):
        is_draft = self.context.get("is_draft")

        trigger_is_function = False
        if data.get("type") == "trigger":
            if data.get("config", {}).get("type") in ["webhook", "manual", "tracking_pixel", "schedule"]:
                trigger_is_function = True
            elif data.get("config", {}).get("type") == "event":
                filters = data.get("config", {}).get("filters", {})
                # Move filter_test_accounts into filters for bytecode compilation
                if data.get("config", {}).get("filter_test_accounts") is not None:
                    filters["filter_test_accounts"] = data["config"].pop("filter_test_accounts")
                if filters:
                    serializer = HogFunctionFiltersSerializer(data=filters, context=self.context)
                    if is_draft:
                        if serializer.is_valid():
                            data["config"]["filters"] = serializer.validated_data
                    else:
                        serializer.is_valid(raise_exception=True)
                        data["config"]["filters"] = serializer.validated_data
            elif data.get("config", {}).get("type") == "batch":
                if not is_draft:
                    filters = data.get("config", {}).get("filters", {})
                    if not filters:
                        raise serializers.ValidationError({"filters": "Filters are required for batch triggers."})
                    if not isinstance(filters, dict):
                        raise serializers.ValidationError({"filters": "Filters must be a dictionary."})
                    properties = filters.get("properties", None)
                    if properties is not None and not isinstance(properties, list):
                        raise serializers.ValidationError({"filters": {"properties": "Properties must be an array."}})
            else:
                if not is_draft:
                    raise serializers.ValidationError({"config": "Invalid trigger type"})

        if "function" in data.get("type", "") or trigger_is_function:
            template_id = data.get("config", {}).get("template_id", "")
            template = HogFunctionTemplate.get_template(template_id)
            if not template:
                if not is_draft:
                    raise serializers.ValidationError({"template_id": "Template not found"})
            else:
                input_schema = template.inputs_schema
                inputs = data.get("config", {}).get("inputs", {})

                function_config_serializer = HogFlowConfigFunctionInputsSerializer(
                    data={
                        "inputs_schema": input_schema,
                        "inputs": inputs,
                    },
                    context={"function_type": template.type},
                )

                if is_draft:
                    if function_config_serializer.is_valid():
                        data["config"]["inputs"] = function_config_serializer.validated_data["inputs"]
                else:
                    function_config_serializer.is_valid(raise_exception=True)
                    data["config"]["inputs"] = function_config_serializer.validated_data["inputs"]

        conditions = data.get("config", {}).get("conditions", [])

        single_condition = data.get("config", {}).get("condition", None)
        if conditions and single_condition:
            if not is_draft:
                raise serializers.ValidationError({"config": "Cannot specify both 'conditions' and 'condition' fields"})
        if single_condition:
            conditions = [single_condition]

        if conditions:
            for condition in conditions:
                filters = condition.get("filters")
                if filters is not None:
                    if "events" in filters:
                        if not is_draft:
                            raise serializers.ValidationError("Event filters are not allowed in conditionals")
                    else:
                        serializer = HogFunctionFiltersSerializer(data=filters, context=self.context)
                        if is_draft:
                            if serializer.is_valid():
                                condition["filters"] = serializer.validated_data
                        else:
                            serializer.is_valid(raise_exception=True)
                            condition["filters"] = serializer.validated_data

        return data


class HogFlowVariableSerializer(serializers.ListSerializer):
    child = serializers.DictField(
        child=serializers.CharField(allow_blank=True),
    )

    def validate(self, attrs):
        # Make sure the keys are unique
        keys = [item.get("key") for item in attrs]
        if len(keys) != len(set(keys)):
            raise serializers.ValidationError("Variable keys must be unique")

        # Make sure entire variables definition is less than 1KB
        # This is just a check for massive keys / default values, we also have a check for dynamically
        # set variables during execution
        total_size = sum(len(json.dumps(item)) for item in attrs)
        if total_size > 1024:
            raise serializers.ValidationError("Total size of variables definition must be less than 1KB")

        return super().validate(attrs)


class HogFlowMaskingSerializer(serializers.Serializer):
    ttl = serializers.IntegerField(
        required=False,
        min_value=60,
        max_value=60 * 60 * 24 * 365 * 3,
        allow_null=True,
        help_text="How long (in seconds) a masked person is remembered before they can re-enter the flow.",
    )
    threshold = serializers.IntegerField(
        required=False,
        allow_null=True,
        help_text="Minimum number of persons that must accumulate before the flow proceeds, for k-anonymity.",
    )
    hash = serializers.CharField(
        required=True,
        help_text="HogQL expression that determines the masking group identity.",
    )
    bytecode = serializers.JSONField(required=False, allow_null=True)

    def validate(self, attrs):
        attrs["bytecode"] = generate_template_bytecode(attrs["hash"], input_collector=set())

        return super().validate(attrs)


class HogFlowMinimalSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)
    trigger = serializers.JSONField(
        read_only=True,
        help_text="Trigger configuration derived from the trigger action's config.",
    )
    trigger_masking = HogFlowMaskingSerializer(
        read_only=True,
        allow_null=True,
        help_text="K-anonymity masking settings applied before the flow starts processing.",
    )
    abort_action = serializers.CharField(
        read_only=True,
        allow_null=True,
        help_text="ID of the action node to execute when the flow is aborted due to an error.",
    )
    edges = HogFlowEdgesField(required=False)
    conversion = HogFlowConversionField(required=False, allow_null=True)
    variables = HogFlowVariablesField(required=False, allow_null=True)

    class Meta:
        model = HogFlow
        fields = [
            "id",
            "name",
            "description",
            "version",
            "status",
            "created_at",
            "created_by",
            "updated_at",
            "trigger",
            "trigger_masking",
            "conversion",
            "exit_condition",
            "edges",
            "actions",
            "abort_action",
            "variables",
            "billable_action_types",
        ]
        read_only_fields = fields


class HogFlowSerializer(HogFlowMinimalSerializer):
    actions = serializers.ListField(child=HogFlowActionSerializer(), required=True)
    trigger_masking = HogFlowMaskingSerializer(
        required=False,
        allow_null=True,
        help_text="K-anonymity masking settings applied before the flow starts processing.",
    )
    variables = HogFlowVariableSerializer(required=False)  # type: ignore[assignment]

    def to_internal_value(self, data):
        status = data.get("status")
        if status is None and self.instance:
            status = self.instance.status
        if status != "active":
            self.context["is_draft"] = True
        return super().to_internal_value(data)

    class Meta:
        model = HogFlow
        fields = [
            "id",
            "name",
            "description",
            "version",
            "status",
            "created_at",
            "created_by",
            "updated_at",
            "trigger",
            "trigger_masking",
            "conversion",
            "exit_condition",
            "edges",
            "actions",
            "abort_action",
            "variables",
            "billable_action_types",
        ]
        read_only_fields = [
            "id",
            "version",
            "created_at",
            "created_by",
            "abort_action",
            "billable_action_types",  # Computed field, not user-editable
        ]

    def validate(self, data):
        instance = cast(Optional[HogFlow], self.instance)
        actions = data.get("actions", instance.actions if instance else [])

        # When activating a draft, re-validate actions from the instance with full (non-draft) checks
        status = data.get("status", instance.status if instance else "draft")
        if status == "active" and instance and instance.status != "active" and "actions" not in data:
            action_serializer = HogFlowActionSerializer(data=instance.actions, many=True, context=self.context)
            action_serializer.is_valid(raise_exception=True)
            actions = action_serializer.validated_data

        # The trigger is derived from the actions. We can trust the action level validation and pull it out
        trigger_actions = [action for action in actions if action.get("type") == "trigger"]

        if len(trigger_actions) != 1:
            raise serializers.ValidationError({"actions": "Exactly one trigger action is required"})

        data["trigger"] = trigger_actions[0]["config"]

        # Compute and store unique billable action types for efficient quota checking
        # Only track billable actions defined in BILLABLE_ACTION_TYPES
        billable_action_types = sorted(
            {action.get("type", "") for action in actions if action.get("type") in BILLABLE_ACTION_TYPES}
        )
        data["billable_action_types"] = billable_action_types

        conversion = data.get("conversion")
        if conversion is not None:
            filters = conversion.get("filters")
            if filters:
                serializer = HogFunctionFiltersSerializer(data={"properties": filters}, context=self.context)
                if self.context.get("is_draft"):
                    if serializer.is_valid():
                        compiled_filters = serializer.validated_data
                        data["conversion"]["filters"] = compiled_filters.get("properties", [])
                        data["conversion"]["bytecode"] = compiled_filters.get("bytecode", [])
                else:
                    serializer.is_valid(raise_exception=True)
                    compiled_filters = serializer.validated_data
                    data["conversion"]["filters"] = compiled_filters.get("properties", [])
                    data["conversion"]["bytecode"] = compiled_filters.get("bytecode", [])
            if "bytecode" not in data["conversion"]:
                data["conversion"]["bytecode"] = []

        return data

    def create(self, validated_data: dict, *args, **kwargs) -> HogFlow:
        request = self.context["request"]
        team_id = self.context["team_id"]
        validated_data["created_by"] = request.user
        validated_data["team_id"] = team_id

        return super().create(validated_data=validated_data)

    def update(self, instance, validated_data):
        return super().update(instance, validated_data)


class HogFlowInvocationSerializer(serializers.Serializer):
    configuration = HogFlowSerializer(write_only=True, required=False)
    globals = serializers.DictField(write_only=True, required=False)
    mock_async_functions = serializers.BooleanField(default=True, write_only=True)
    current_action_id = serializers.CharField(write_only=True, required=False)


class HogFlowBulkDeleteRequestSerializer(serializers.Serializer):
    ids = serializers.ListField(
        child=serializers.UUIDField(),
        allow_empty=False,
        help_text="List of workflow IDs to delete.",
    )


class HogFlowBulkDeleteResponseSerializer(serializers.Serializer):
    deleted = serializers.IntegerField(help_text="Number of workflows deleted.")


class CommaSeparatedListFilter(BaseInFilter, CharFilter):
    pass


class HogFlowFilterSet(FilterSet):
    class Meta:
        model = HogFlow
        fields = ["id", "created_by", "created_at", "updated_at"]


@extend_schema_view(
    list=extend_schema(
        summary="List workflows",
        description=(
            "Returns all workflows for the team, ordered by most recently updated. "
            "Use the HogQL hog_flows table for richer filtering and aggregation."
        ),
    ),
    retrieve=extend_schema(
        summary="Get a workflow",
        description="Returns the full workflow definition including trigger, edges, actions, exit condition, and variables.",
    ),
    create=extend_schema(
        summary="Create a workflow",
        description=(
            "Create a new workflow. The actions array must contain exactly one action with type='trigger'. "
            "All other actions define the flow steps; connect them via the edges array. "
            "The workflow is created in 'draft' status; set status='active' to activate it."
        ),
    ),
    partial_update=extend_schema(
        summary="Update a workflow",
        description=(
            "Update workflow fields. "
            "Set status='active' to activate a draft workflow, or status='archived' to archive it. "
            "Only changed fields need to be included."
        ),
    ),
    destroy=extend_schema(
        summary="Delete a workflow",
        description=(
            "Permanently delete an archived workflow. "
            "Prefer archiving (status='archived' via partial update) over deletion to preserve audit history."
        ),
    ),
)
class HogFlowViewSet(TeamAndOrgViewSetMixin, LogEntryMixin, AppMetricsMixin, viewsets.ModelViewSet):
    scope_object = "hog_flow"
    queryset = HogFlow.objects.all()
    filter_backends = [DjangoFilterBackend]
    filterset_class = HogFlowFilterSet
    log_source = "hog_flow"
    app_source = "hog_flow"

    def get_serializer_class(self) -> type[BaseSerializer]:
        return HogFlowMinimalSerializer if self.action == "list" else HogFlowSerializer

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        if self.action == "list":
            queryset = queryset.order_by("-updated_at")

        if self.request.GET.get("trigger"):
            try:
                trigger = json.loads(self.request.GET["trigger"])

                if trigger:
                    queryset = queryset.filter(trigger__contains=trigger)
            except (ValueError, KeyError, TypeError):
                raise exceptions.ValidationError({"trigger": "Invalid trigger"})

        return queryset

    def safely_get_object(self, queryset):
        # TODO(team-workflows): Somehow implement version lookups
        return super().safely_get_object(queryset)

    def perform_create(self, serializer):
        serializer.save()
        log_activity_from_viewset(self, serializer.instance, name=serializer.instance.name, detail_type="standard")

        try:
            # Count edges and actions
            edges_count = len(serializer.instance.edges) if serializer.instance.edges else 0
            actions_count = len(serializer.instance.actions) if serializer.instance.actions else 0

            posthoganalytics.capture(
                distinct_id=str(serializer.context["request"].user.distinct_id),
                event="hog_flow_created",
                properties={
                    "workflow_id": str(serializer.instance.id),
                    "workflow_name": serializer.instance.name,
                    # "trigger_type": trigger_type,
                    "edges_count": edges_count,
                    "actions_count": actions_count,
                    "team_id": str(self.team_id),
                    "organization_id": str(self.organization.id),
                },
            )
        except Exception as e:
            logger.warning("Failed to capture hog_flow_created event", error=str(e))

    def perform_update(self, serializer):
        # TODO(team-workflows): Atomically increment version, insert new object instead of default update behavior
        instance_id = serializer.instance.id

        try:
            # nosemgrep: idor-lookup-without-team (re-fetch of already-authorized instance for activity logging)
            before_update = HogFlow.objects.get(pk=instance_id)
        except HogFlow.DoesNotExist:
            before_update = None

        serializer.save()

        log_activity_from_viewset(self, serializer.instance, name=serializer.instance.name, previous=before_update)

        # PostHog capture for hog_flow activated (draft -> active)
        if (
            before_update
            and before_update.status == HogFlow.State.DRAFT
            and serializer.instance.status == HogFlow.State.ACTIVE
        ):
            try:
                # Count edges and actions
                edges_count = len(serializer.instance.edges) if serializer.instance.edges else 0
                actions_count = len(serializer.instance.actions) if serializer.instance.actions else 0

                posthoganalytics.capture(
                    distinct_id=str(serializer.context["request"].user.distinct_id),
                    event="hog_flow_activated",
                    properties={
                        "workflow_id": str(serializer.instance.id),
                        "workflow_name": serializer.instance.name,
                        "edges_count": edges_count,
                        "actions_count": actions_count,
                        "team_id": str(self.team_id),
                        "organization_id": str(self.organization.id),
                    },
                )
            except Exception as e:
                logger.warning("Failed to capture hog_flow_activated event", error=str(e))

    @action(detail=True, methods=["POST"])
    def invocations(self, request: Request, *args, **kwargs):
        try:
            hog_flow = self.get_object()
        except Exception:
            hog_flow = None

        serializer = HogFlowInvocationSerializer(
            data=request.data, context={**self.get_serializer_context(), "instance": hog_flow}
        )
        if not serializer.is_valid():
            return Response(serializer.errors, status=400)

        res = create_hog_flow_invocation_test(
            team_id=self.team_id,
            hog_flow_id=str(hog_flow.id) if hog_flow else "new",
            payload=serializer.validated_data,
        )

        if res.status_code != 200:
            return Response({"status": "error", "message": res.json()["error"]}, status=res.status_code)

        return Response(res.json())

    @action(methods=["POST"], detail=False)
    def user_blast_radius(self, request: Request, **kwargs):
        if "filters" not in request.data:
            raise exceptions.ValidationError("Missing filters for which to get blast radius")

        filters = request.data.get("filters", {})
        group_type_index = request.data.get("group_type_index", None)

        users_affected, total_users = get_user_blast_radius(self.team, filters, group_type_index)

        return Response(
            {
                "users_affected": users_affected,
                "total_users": total_users,
            }
        )

    @extend_schema(
        summary="Bulk delete workflows",
        description="Permanently delete multiple archived workflows by their IDs. Only archived workflows can be deleted.",
        request=HogFlowBulkDeleteRequestSerializer,
        responses={200: HogFlowBulkDeleteResponseSerializer},
    )
    @action(methods=["POST"], detail=False, required_scopes=["hog_flow:write"])
    def bulk_delete(self, request: Request, **kwargs):
        serializer = HogFlowBulkDeleteRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        queryset = self.get_queryset().filter(id__in=serializer.validated_data["ids"], status="archived")
        deleted_count, _ = queryset.delete()

        return Response({"deleted": deleted_count})

    @action(detail=True, methods=["GET", "POST"])
    def batch_jobs(self, request: Request, *args, **kwargs):
        try:
            hog_flow = self.get_object()
        except Exception:
            raise exceptions.NotFound(f"Workflow {kwargs.get('pk')} not found")

        if request.method == "POST":
            serializer = HogFlowBatchJobSerializer(
                data={**request.data, "hog_flow": hog_flow.id}, context={**self.get_serializer_context()}
            )
            if not serializer.is_valid():
                return Response(serializer.errors, status=400)

            batch_job = serializer.save()
            return Response(HogFlowBatchJobSerializer(batch_job).data)
        else:
            batch_jobs = HogFlowBatchJob.objects.filter(hog_flow=hog_flow, team=self.team).order_by("-created_at")
            serializer = HogFlowBatchJobSerializer(batch_jobs, many=True)
            return Response(serializer.data)


class InternalHogFlowViewSet(TeamAndOrgViewSetMixin, LogEntryMixin, AppMetricsMixin, viewsets.ModelViewSet):
    """
    Internal endpoints for Node.js services to query user blast radius.
    These endpoints require Bearer token authentication via INTERNAL_API_SECRET and are not exposed to Contour ingress
    """

    scope_object = "INTERNAL"
    authentication_classes = [InternalAPIAuthentication]

    # Internal service-to-service endpoints (authenticated with INTERNAL_API_SECRET)
    def internal_user_blast_radius(self, request: Request, team_id: str) -> Response:
        """
        Internal endpoint for Node.js services to query user blast radius.
        Requires Bearer token authentication via INTERNAL_API_SECRET.
        """

        if request.method != "POST":
            return Response({"error": "Method not allowed"}, status=405)

        try:
            team = Team.objects.get(id=int(team_id))
        except (Team.DoesNotExist, ValueError):
            return Response({"error": "Team not found"}, status=404)

        if "filters" not in request.data:
            return Response({"error": "Missing filters for which to get blast radius"}, status=400)

        filters = request.data.get("filters", {})
        group_type_index = request.data.get("group_type_index", None)

        try:
            users_affected, total_users = get_user_blast_radius(team, filters, group_type_index)
            return Response(
                {
                    "users_affected": users_affected,
                    "total_users": total_users,
                }
            )
        except Exception as e:
            logger.exception("Error in internal_user_blast_radius", error=str(e), team_id=team_id)
            return Response({"error": "Internal server error"}, status=500)

    def internal_user_blast_radius_persons(self, request: Request, team_id: str) -> Response:
        """
        Internal endpoint for Node.js services to query user blast radius persons with pagination.
        Requires Bearer token authentication via INTERNAL_API_SECRET.
        """
        if request.method != "POST":
            return Response({"error": "Method not allowed"}, status=405)

        try:
            team = Team.objects.get(id=int(team_id))
        except (Team.DoesNotExist, ValueError):
            return Response({"error": "Team not found"}, status=404)

        if "filters" not in request.data:
            return Response({"error": "Missing filters for which to get blast radius"}, status=400)

        filters = request.data.get("filters", {}) or {}
        group_type_index = request.data.get("group_type_index", None)
        cursor = request.data.get("cursor", None)

        try:
            users_affected = get_user_blast_radius_persons(team, filters, group_type_index, cursor)
            return Response(
                {
                    "users_affected": users_affected,
                    "cursor": users_affected[-1] if users_affected else None,
                    "has_more": len(users_affected) == PERSON_BATCH_SIZE,
                }
            )
        except Exception as e:
            logger.exception("Error in internal_user_blast_radius_persons", error=str(e), team_id=team_id)
            return Response({"error": "Internal server error"}, status=500)
