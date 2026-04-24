import re
import json
import uuid as uuid_mod
from datetime import timedelta
from typing import Optional, cast

from django.db.models import QuerySet
from django.utils import timezone

import structlog
import posthoganalytics
from django_filters import BaseInFilter, CharFilter, FilterSet
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import exceptions, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.serializers import BaseSerializer

from posthog.api.app_metrics2 import AppMetricsMixin
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
from posthog.plugins.plugin_server_api import create_hog_flow_invocation_test, create_hog_flow_scheduled_invocation

from products.workflows.backend.models.hog_flow_batch_job import HogFlowBatchJob
from products.workflows.backend.models.hog_flow_schedule import SCHEDULED_TRIGGER_TYPES, HogFlowSchedule
from products.workflows.backend.utils.rrule_utils import compute_next_occurrences, validate_rrule

logger = structlog.get_logger(__name__)

# Delay durations are strings like "30m", "2h", "1.5d". Must match the regex in the Node.js executor
# (nodejs/src/cdp/services/hogflows/actions/delay.ts) that throws at runtime on mismatch.
DELAY_DURATION_REGEX = re.compile(r"^\d*\.?\d+[dhm]$")


class BlastRadiusRequestSerializer(serializers.Serializer):
    filters = serializers.DictField(help_text="Property filters to apply")
    group_type_index = serializers.IntegerField(
        required=False, allow_null=True, help_text="Group type index for group-based targeting"
    )


class BlastRadiusSerializer(serializers.Serializer):
    affected = serializers.IntegerField(help_text="Number of users matching the filters")
    total = serializers.IntegerField(help_text="Total number of users")


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
    created_at = serializers.IntegerField(required=False)
    updated_at = serializers.IntegerField(required=False)
    filters = HogFunctionFiltersSerializer(required=False, default=None, allow_null=True)
    type = serializers.CharField(max_length=100)
    config = serializers.JSONField()
    output_variable = serializers.JSONField(required=False, allow_null=True)

    def to_internal_value(self, data):
        # Weirdly nested serializers don't get this set...
        self.initial_data = data
        return super().to_internal_value(data)

    def validate(self, data):
        is_draft = self.context.get("is_draft")

        trigger_is_function = False
        if data.get("type") == "trigger":
            if data.get("config", {}).get("type") in ["webhook", "manual", "tracking_pixel"]:
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
            elif data.get("config", {}).get("type") == "schedule":
                # Schedule triggers have no extra validation - the schedule definition
                # lives on a separate HogFlowSchedule row keyed by hog_flow_id.
                pass
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

        if data.get("type") == "delay":
            delay_duration = data.get("config", {}).get("delay_duration")
            if not isinstance(delay_duration, str) or not DELAY_DURATION_REGEX.match(delay_duration):
                if not is_draft:
                    raise serializers.ValidationError(
                        {
                            "config": (
                                "delay_duration must be a string matching ^\\d*\\.?\\d+[dhm]$ "
                                "(e.g. '30m', '2h', '1d'). Seconds and ISO-8601 formats are not supported."
                            )
                        }
                    )

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

        # Make sure entire variables definition is less than 5KB
        # This is just a check for massive keys / default values, we also have a check for dynamically
        # set variables during execution
        total_size = sum(len(json.dumps(item)) for item in attrs)
        if total_size > 5120:
            raise serializers.ValidationError("Total size of variables definition must be less than 5KB")

        return super().validate(attrs)


class HogFlowMaskingSerializer(serializers.Serializer):
    ttl = serializers.IntegerField(required=False, min_value=60, max_value=60 * 60 * 24 * 365 * 3, allow_null=True)
    threshold = serializers.IntegerField(required=False, allow_null=True)
    hash = serializers.CharField(required=True)
    bytecode = serializers.JSONField(required=False, allow_null=True)

    def validate(self, attrs):
        attrs["bytecode"] = generate_template_bytecode(attrs["hash"], input_collector=set())

        return super().validate(attrs)


class HogFlowScheduleSerializer(serializers.ModelSerializer):
    class Meta:
        model = HogFlowSchedule
        fields = [
            "id",
            "rrule",
            "starts_at",
            "timezone",
            "variables",
            "status",
            "next_run_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "status", "next_run_at", "created_at", "updated_at"]

    def validate(self, data):
        # For partial updates, fall back to instance values
        instance = self.instance
        rrule_str = data.get("rrule", getattr(instance, "rrule", None))
        starts_at = data.get("starts_at", getattr(instance, "starts_at", None))
        timezone_str = data.get("timezone", getattr(instance, "timezone", "UTC"))

        if not rrule_str:
            raise serializers.ValidationError({"rrule": "RRULE string is required."})

        if "rrule" in data:
            try:
                validate_rrule(rrule_str)
            except (ValueError, TypeError) as e:
                logger.warning("Invalid RRULE encountered during validation", rrule=rrule_str, error=str(e))
                raise serializers.ValidationError({"rrule": "Invalid RRULE."})

        if not starts_at:
            raise serializers.ValidationError({"starts_at": "Start date is required."})

        try:
            sample = compute_next_occurrences(rrule_str, starts_at, timezone_str=timezone_str, count=2)
        except (KeyError, ValueError):
            raise serializers.ValidationError({"timezone": "Invalid or unknown timezone."})

        if len(sample) == 0:
            raise serializers.ValidationError({"rrule": "Schedule produces no future occurrences."})
        if len(sample) == 2 and (sample[1] - sample[0]) < timedelta(hours=1):
            raise serializers.ValidationError({"rrule": "Schedules must run at most once per hour."})

        return data

    def update(self, instance, validated_data):
        if any(field in validated_data for field in ("rrule", "starts_at", "timezone")):
            # Force the scheduler to recalculate the next occurrence on its next poll
            instance.next_run_at = None
            if instance.status != HogFlowSchedule.Status.PAUSED:
                instance.status = HogFlowSchedule.Status.ACTIVE
        return super().update(instance, validated_data)


class HogFlowMinimalSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)

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
    trigger_masking = HogFlowMaskingSerializer(required=False, allow_null=True)
    variables = HogFlowVariableSerializer(required=False)

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


class CommaSeparatedListFilter(BaseInFilter, CharFilter):
    pass


class HogFlowFilterSet(FilterSet):
    class Meta:
        model = HogFlow
        fields = ["id", "created_by", "created_at", "updated_at"]


@extend_schema(tags=["workflows"])
class HogFlowViewSet(TeamAndOrgViewSetMixin, LogEntryMixin, AppMetricsMixin, viewsets.ModelViewSet):
    scope_object = "hog_flow"
    scope_object_read_actions = ["list", "retrieve", "logs", "metrics", "metrics_totals"]
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
                raise exceptions.ValidationError({"trigger": f"Invalid trigger"})

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
            # nosemgrep: semgrep.rules.idor-lookup-without-team (re-fetch of already-authorized instance for activity logging)
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

    @extend_schema(request=BlastRadiusRequestSerializer, responses=BlastRadiusSerializer)
    @action(methods=["POST"], detail=False)
    def user_blast_radius(self, request: Request, **kwargs):
        if "filters" not in request.data:
            raise exceptions.ValidationError("Missing filters for which to get blast radius")

        filters = request.data.get("filters", {})
        group_type_index = request.data.get("group_type_index", None)

        result = get_user_blast_radius(self.team, filters, group_type_index)

        return Response(BlastRadiusSerializer(result).data)

    @action(methods=["POST"], detail=False)
    def bulk_delete(self, request: Request, **kwargs):
        ids = request.data.get("ids", [])
        if not ids or not isinstance(ids, list):
            return Response({"error": "A non-empty list of 'ids' is required"}, status=400)

        try:
            validated_ids = [uuid_mod.UUID(str(id)) for id in ids]
        except ValueError:
            return Response({"error": "One or more IDs are not valid UUIDs"}, status=400)

        queryset = self.get_queryset().filter(id__in=validated_ids, status="archived")
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

    @extend_schema(responses=HogFlowScheduleSerializer(many=True))
    @action(detail=True, methods=["GET", "POST"])
    def schedules(self, request: Request, *args, **kwargs):
        hog_flow = self.get_object()

        if request.method == "POST":
            serializer = HogFlowScheduleSerializer(data=request.data, context=self.get_serializer_context())
            serializer.is_valid(raise_exception=True)
            serializer.save(team=self.team, hog_flow=hog_flow)
            return Response(serializer.data, status=201)

        schedules = HogFlowSchedule.objects.filter(hog_flow=hog_flow, team=self.team).order_by("-created_at")
        serializer = HogFlowScheduleSerializer(schedules, many=True)
        return Response(serializer.data)

    @extend_schema(parameters=[OpenApiParameter("schedule_id", str, OpenApiParameter.PATH)])
    @action(detail=True, methods=["PATCH", "DELETE"], url_path="schedules/(?P<schedule_id>[^/.]+)")
    def schedule_detail(self, request: Request, schedule_id=None, *args, **kwargs):
        hog_flow = self.get_object()
        try:
            schedule = HogFlowSchedule.objects.get(id=schedule_id, hog_flow=hog_flow, team=self.team)
        except HogFlowSchedule.DoesNotExist:
            raise exceptions.NotFound("Schedule not found")

        if request.method == "DELETE":
            schedule.delete()
            return Response(status=204)

        serializer = HogFlowScheduleSerializer(
            schedule, data=request.data, partial=True, context=self.get_serializer_context()
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
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
            result = get_user_blast_radius(team, filters, group_type_index)
            return Response(BlastRadiusSerializer(result).data)
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

    def internal_process_due_schedules(self, request: Request, **kwargs) -> Response:
        """
        Internal endpoint called by the scheduler service to process due schedules.
        Handles both executing due schedules and initializing next_run_at for new ones.
        """
        from django.db import transaction

        from products.workflows.backend.models.hog_flow_batch_job import HogFlowBatchJob
        from products.workflows.backend.models.hog_flow_schedule import HogFlowSchedule
        from products.workflows.backend.utils.rrule_utils import compute_next_occurrences

        def advance_next_run(schedule, after=None):
            """Compute and set next_run_at, or mark completed if RRULE is exhausted."""
            occurrences = compute_next_occurrences(
                rrule_string=schedule.rrule,
                starts_at=schedule.starts_at,
                timezone_str=schedule.timezone,
                after=after,
                count=1,
            )
            if occurrences:
                schedule.next_run_at = occurrences[0]
                schedule.save(update_fields=["next_run_at", "updated_at"])
            else:
                schedule.status = HogFlowSchedule.Status.COMPLETED
                schedule.next_run_at = None
                schedule.save(update_fields=["status", "next_run_at", "updated_at"])
            return occurrences

        def resolve_variables(hog_flow, schedule):
            """Build default variables from HogFlow schema, then merge schedule overrides."""
            variables = {}
            for var in hog_flow.variables or []:
                variables[var.get("key")] = var.get("default")
            variables.update(schedule.variables or {})
            return variables

        processed = []
        initialized = []
        failed = []

        try:
            # 1. Process due schedules (next_run_at <= now)
            # nosemgrep: semgrep.rules.idor-lookup-without-team (internal endpoint processes all teams)
            due_schedule_ids = list(
                HogFlowSchedule.objects.filter(
                    status=HogFlowSchedule.Status.ACTIVE, next_run_at__lte=timezone.now()
                ).values_list("id", flat=True)
            )

            for schedule_id in due_schedule_ids:
                try:
                    batch_job_params: dict | None = None
                    schedule_invocation_params: dict | None = None
                    with transaction.atomic():
                        # Per-schedule transaction: lock only one row at a time to minimize
                        # lock duration and allow concurrent replicas via skip_locked.
                        # Re-checks conditions since the schedule may have been processed
                        # between the ID scan and this lock.
                        schedule = (
                            # nosemgrep: semgrep.rules.idor-lookup-without-team
                            HogFlowSchedule.objects.select_for_update(skip_locked=True)
                            .select_related("hog_flow")
                            .filter(
                                id=schedule_id, status=HogFlowSchedule.Status.ACTIVE, next_run_at__lte=timezone.now()
                            )
                            .first()
                        )
                        if not schedule:
                            continue

                        hog_flow = schedule.hog_flow
                        trigger_type = (hog_flow.trigger or {}).get("type")

                        if hog_flow.status != "active" or trigger_type not in SCHEDULED_TRIGGER_TYPES:
                            schedule.next_run_at = None
                            schedule.save(update_fields=["next_run_at", "updated_at"])
                            continue

                        advance_next_run(schedule, after=schedule.next_run_at)

                        if trigger_type == "batch":
                            batch_job_params = {
                                "team_id": schedule.team_id,
                                "hog_flow": hog_flow,
                                "variables": resolve_variables(hog_flow, schedule),
                                "filters": (hog_flow.trigger or {}).get("filters", {}),
                            }
                        else:
                            schedule_invocation_params = {
                                "team_id": schedule.team_id,
                                "hog_flow_id": str(hog_flow.id),
                                "variables": resolve_variables(hog_flow, schedule),
                            }

                    # Dispatch outside the transaction so HTTP calls don't hold the row lock.
                    if batch_job_params:
                        HogFlowBatchJob.objects.create(
                            **batch_job_params,
                            status=HogFlowBatchJob.State.QUEUED,
                        )
                        processed.append(str(schedule_id))
                    elif schedule_invocation_params:
                        response = create_hog_flow_scheduled_invocation(**schedule_invocation_params)
                        response.raise_for_status()
                        processed.append(str(schedule_id))
                except Exception:
                    logger.exception("Error processing schedule", schedule_id=str(schedule_id))
                    failed.append(str(schedule_id))

            # 2. Initialize next_run_at for schedules that need it
            # nosemgrep: semgrep.rules.idor-lookup-without-team (internal endpoint processes all teams)
            uninitialized_ids = list(
                HogFlowSchedule.objects.filter(
                    status=HogFlowSchedule.Status.ACTIVE,
                    next_run_at__isnull=True,
                    hog_flow__status="active",
                    hog_flow__trigger__type__in=SCHEDULED_TRIGGER_TYPES,
                ).values_list("id", flat=True)
            )

            for schedule_id in uninitialized_ids:
                try:
                    with transaction.atomic():
                        # Per-schedule transaction: lock only one row at a time to minimize
                        # lock duration and allow concurrent replicas via skip_locked.
                        # Re-checks conditions since the schedule may have been initialized
                        # between the ID scan and this lock.
                        schedule = (
                            # nosemgrep: semgrep.rules.idor-lookup-without-team
                            HogFlowSchedule.objects.select_for_update(skip_locked=True)
                            .filter(id=schedule_id, status=HogFlowSchedule.Status.ACTIVE, next_run_at__isnull=True)
                            .first()
                        )
                        if not schedule:
                            continue

                        if advance_next_run(schedule):
                            initialized.append(str(schedule.id))
                except Exception:
                    logger.exception("Error initializing schedule", schedule_id=str(schedule_id))
                    failed.append(str(schedule_id))

            return Response(
                {
                    "processed": processed,
                    "initialized": initialized,
                    "failed": failed,
                }
            )
        except Exception as e:
            logger.exception("Error in internal_process_due_schedules", error=str(e))
            return Response({"error": "Internal server error"}, status=500)
