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
from posthog.api.documentation import _FallbackSerializer
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
from posthog.plugins.plugin_server_api import (
    bulk_replay_hog_flow_invocations,
    create_hog_flow_invocation_test,
    create_hog_flow_scheduled_invocation,
)

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

    _ACTION_ID_PATTERN = re.compile(r"\[Action:([a-zA-Z0-9_-]+)\]")
    _EVENT_UUID_PATTERN = re.compile(r"for event ([a-f0-9-]{36})")

    # Restricted to the 2026-04 dedup incident fingerprint to avoid replaying legitimate
    # dedup catches (ghost runs caused by Kafka rebalance re-deliveries). See inline
    # comments on each clause for the reasoning.
    BLOCKED_RUNS_SQL = r"""
        SELECT instance_id, timestamp, message
        FROM log_entries
        WHERE team_id = %(team_id)s
          AND log_source = 'hog_flow'
          AND log_source_id = %(log_source_id)s
          AND positionCaseInsensitiveUTF8(message, 'duplicate execution detected') > 0

          -- Incident window: dedup shipped 2026-03-30 evening UTC and was reverted on
          -- 2026-04-22 morning UTC. No bug-pattern blocks can exist outside this window.
          AND timestamp >= toDateTime('2026-03-30 00:00:00')
          AND timestamp <= toDateTime('2026-04-23 00:00:00')

          -- Clause 1: action restricted to wait_until_condition, the only "hold-state"
          -- action where the bug could fire dedup falsely. Other actions (delay, function
          -- async, conditional_branch with delay) advance state.currentAction on resume,
          -- so dedup never re-checks the same key. Blocks on those action types in this
          -- window were legitimate ghost catches and must NOT be replayed.
          AND positionUTF8(message, '[Action:action_wait_until_condition_') > 0

          -- Clause 2: blocked instance_id must be uuidv7. The bug rewrote the original
          -- UUIDT id to uuidv7 when the paused invocation was re-queued through
          -- Cyclotron's V1 Postgres path. Position 15 (1-indexed) is the version nibble;
          -- position 20 is the RFC-4122 variant nibble.
          AND lower(substring(instance_id, 15, 1)) = '7'
          AND lower(substring(instance_id, 20, 1)) IN ('8', '9', 'a', 'b')

          -- Clause 3: if the message exposes 'Another invocation (<uuid>)' (post-2026-04-21
          -- log format), that stored id must be UUIDT, not uuidv7. Pre-2026-04-21 messages
          -- don't include this clause; the extract returns empty and the row stays in via
          -- clause 2 alone.
          AND (
              extract(message, 'Another invocation \(([a-fA-F0-9-]{36})\)') = ''
              OR lower(substring(extract(message, 'Another invocation \(([a-fA-F0-9-]{36})\)'), 15, 1)) != '7'
          )

          -- Clause 4: the uuidv7's embedded ms timestamp (first 12 hex chars) must fall
          -- within 15 minutes before the block. Real bug rewrites mint a fresh uuidv7 at
          -- re-queue time, and wait_until_condition's re-check interval
          -- (DEFAULT_WAIT_DURATION_SECONDS = 600s = 10 min) bounds the gap. This
          -- proximity check guards against any non-uuidv7 id that happens to share the
          -- version + variant nibble pattern by coincidence.
          AND fromUnixTimestamp64Milli(
                  reinterpretAsInt64(reverse(unhex(substring(replaceAll(instance_id, '-', ''), 1, 12))))
              ) >= subtractMinutes(timestamp, 15)
          AND fromUnixTimestamp64Milli(
                  reinterpretAsInt64(reverse(unhex(substring(replaceAll(instance_id, '-', ''), 1, 12))))
              ) <= timestamp

          -- Exclude rows already queued for replay. The Node CDP API writes this marker
          -- when bulk_replay_invocations succeeds.
          AND instance_id NOT IN (
              SELECT instance_id
              FROM log_entries
              WHERE team_id = %(team_id)s
                AND log_source = 'hog_flow'
                AND log_source_id = %(log_source_id)s
                AND positionCaseInsensitiveUTF8(message, '[Replay] Queued') > 0
          )
        ORDER BY timestamp DESC
    """

    REPLAY_EVENT_SQL = """
        SELECT
            uuid,
            event,
            properties,
            timestamp,
            team_id,
            distinct_id,
            elements_chain,
            person_id,
            person_properties,
            group0_properties,
            group1_properties,
            group2_properties,
            group3_properties,
            group4_properties
        FROM events
        WHERE uuid = %(event_id)s AND team_id = %(team_id)s
    """

    def _is_replay_feature_enabled(self) -> bool:
        from posthog.models.feature_flag import FeatureFlag

        return FeatureFlag.objects.filter(
            team_id=self.team_id, key="workflows-replay-blocked-runs", active=True
        ).exists()

    def _parse_blocked_run_message(self, message: str) -> tuple[Optional[str], Optional[str]]:
        action_match = self._ACTION_ID_PATTERN.search(message)
        event_match = self._EVENT_UUID_PATTERN.search(message)
        return (
            action_match.group(1) if action_match else None,
            event_match.group(1) if event_match else None,
        )

    def _fetch_clickhouse_event(self, event_uuid: str) -> Optional[dict]:
        """Fetch a single event from ClickHouse and return it as a dict for the Node CDP API."""
        from posthog.clickhouse.client.execute import sync_execute

        event_results = sync_execute(
            self.REPLAY_EVENT_SQL,
            {"event_id": event_uuid, "team_id": self.team_id},
            with_column_types=True,
        )

        rows, columns = event_results
        if not rows:
            return None

        col_names = [col[0] for col in columns]
        row = dict(zip(col_names, rows[0]))

        return {
            "uuid": str(row["uuid"]),
            "event": row["event"],
            "properties": row["properties"],
            "timestamp": row["timestamp"].isoformat()
            if hasattr(row["timestamp"], "isoformat")
            else str(row["timestamp"]),
            "team_id": row["team_id"],
            "distinct_id": row["distinct_id"],
            "elements_chain": row["elements_chain"] or "",
            "person_id": str(row["person_id"]) if row.get("person_id") else None,
            "person_properties": row.get("person_properties", ""),
            "group0_properties": row.get("group0_properties", ""),
            "group1_properties": row.get("group1_properties", ""),
            "group2_properties": row.get("group2_properties", ""),
            "group3_properties": row.get("group3_properties", ""),
            "group4_properties": row.get("group4_properties", ""),
        }

    @action(detail=True, methods=["GET"], url_path="blocked_runs")
    def blocked_runs(self, request: Request, *args, **kwargs):
        """List workflow runs that were blocked by the dedup bug."""
        from posthog.clickhouse.client.execute import sync_execute

        if not self._is_replay_feature_enabled():
            return Response({"results": []})

        hog_flow = self.get_object()

        try:
            limit = min(int(request.query_params.get("limit", 100)), 1000)
        except ValueError:
            return Response({"error": "limit must be an integer"}, status=400)

        try:
            offset = max(int(request.query_params.get("offset", 0)), 0)
        except ValueError:
            return Response({"error": "offset must be an integer"}, status=400)

        query = self.BLOCKED_RUNS_SQL + "\nLIMIT %(limit)s\nOFFSET %(offset)s"
        results = sync_execute(
            query,
            {"team_id": self.team_id, "log_source_id": str(hog_flow.id), "limit": limit + 1, "offset": offset},
        )

        has_next = len(results) > limit
        results = results[:limit]

        blocked_runs = []
        for instance_id, timestamp, message in results:
            action_id, event_uuid = self._parse_blocked_run_message(message)
            blocked_runs.append(
                {
                    "instance_id": instance_id,
                    "timestamp": timestamp.isoformat() if hasattr(timestamp, "isoformat") else str(timestamp),
                    "action_id": action_id,
                    "event_uuid": event_uuid,
                    "message": message,
                }
            )

        return Response({"results": blocked_runs, "has_next": has_next, "limit": limit, "offset": offset})

    @action(detail=True, methods=["POST"], url_path="replay_blocked_run")
    def replay_blocked_run(self, request: Request, *args, **kwargs):
        """Replay a single blocked run. Django fetches the event, Node creates the invocation and writes the log."""
        if not self._is_replay_feature_enabled():
            return Response({"error": "This feature is not enabled"}, status=403)

        hog_flow = self.get_object()

        event_uuid = request.data.get("event_uuid")
        action_id = request.data.get("action_id")
        instance_id = request.data.get("instance_id")

        if not event_uuid or not action_id or not instance_id:
            return Response({"error": "event_uuid, action_id, and instance_id are required"}, status=400)

        # Validate instance_id belongs to a blocked run for this workflow
        from posthog.clickhouse.client.execute import sync_execute

        validation_result = sync_execute(
            """
            SELECT message
            FROM log_entries
            WHERE team_id = %(team_id)s
              AND log_source = 'hog_flow'
              AND log_source_id = %(log_source_id)s
              AND instance_id = %(instance_id)s
              AND positionCaseInsensitiveUTF8(message, 'duplicate execution detected') > 0
              AND timestamp >= toDate(NOW() - INTERVAL 30 DAY)
            LIMIT 1
            """,
            {"team_id": self.team_id, "log_source_id": str(hog_flow.id), "instance_id": instance_id},
        )
        if not validation_result:
            return Response({"error": f"Blocked run {instance_id} not found for this workflow"}, status=404)

        _, logged_event_uuid = self._parse_blocked_run_message(validation_result[0][0])
        if logged_event_uuid != event_uuid:
            return Response({"error": "event_uuid does not match the blocked run"}, status=400)

        clickhouse_event = self._fetch_clickhouse_event(event_uuid)
        if not clickhouse_event:
            return Response({"error": f"Event {event_uuid} not found"}, status=404)

        res = bulk_replay_hog_flow_invocations(
            team_id=self.team_id,
            hog_flow_id=str(hog_flow.id),
            items=[{"clickhouse_event": clickhouse_event, "action_id": action_id, "instance_id": instance_id}],
        )

        if res.status_code != 200:
            return Response({"status": "error", "message": res.json().get("error")}, status=res.status_code)

        result = res.json()
        if result.get("succeeded", 0) > 0:
            return Response({"status": "queued"})
        return Response({"status": "error", "message": "Failed to replay run"}, status=400)

    @action(detail=True, methods=["POST"], url_path="replay_all_blocked_runs")
    def replay_all_blocked_runs(self, request: Request, *args, **kwargs):
        """Replay all blocked runs in a single bulk call to Node."""
        from posthog.clickhouse.client.execute import sync_execute

        if not self._is_replay_feature_enabled():
            return Response({"error": "This feature is not enabled"}, status=403)

        hog_flow = self.get_object()

        results = sync_execute(
            self.BLOCKED_RUNS_SQL,
            {"team_id": self.team_id, "log_source_id": str(hog_flow.id)},
        )

        # Parse blocked runs and collect event UUIDs
        blocked_runs: list[tuple[str, str, str]] = []  # (instance_id, action_id, event_uuid)
        skipped = 0
        for instance_id, _timestamp, message in results:
            action_id, event_uuid = self._parse_blocked_run_message(message)
            if not action_id or not event_uuid:
                skipped += 1
                continue
            blocked_runs.append((instance_id, action_id, event_uuid))

        if not blocked_runs:
            return Response({"succeeded": 0, "failed": 0, "skipped": skipped})

        # Process in batches to avoid large ClickHouse IN clauses (uuid is not a primary key)
        # and HTTP timeouts/memory pressure on the Node side
        batch_size = 100
        succeeded = 0
        failed = 0
        hog_flow_id = str(hog_flow.id)

        batch_event_query = """
            SELECT
                uuid, event, properties, timestamp, team_id, distinct_id,
                elements_chain, person_id, person_properties,
                group0_properties, group1_properties, group2_properties,
                group3_properties, group4_properties
            FROM events
            WHERE uuid IN %(event_ids)s AND team_id = %(team_id)s
        """

        for i in range(0, len(blocked_runs), batch_size):
            batch = blocked_runs[i : i + batch_size]
            unique_event_uuids = list({event_uuid for _, _, event_uuid in batch})

            event_results = sync_execute(
                batch_event_query,
                {"event_ids": unique_event_uuids, "team_id": self.team_id},
                with_column_types=True,
            )

            event_rows, event_columns = event_results
            col_names = [col[0] for col in event_columns]
            events_by_uuid: dict[str, dict] = {}
            for row_data in event_rows:
                row = dict(zip(col_names, row_data))
                events_by_uuid[str(row["uuid"])] = {
                    "uuid": str(row["uuid"]),
                    "event": row["event"],
                    "properties": row["properties"],
                    "timestamp": row["timestamp"].isoformat()
                    if hasattr(row["timestamp"], "isoformat")
                    else str(row["timestamp"]),
                    "team_id": row["team_id"],
                    "distinct_id": row["distinct_id"],
                    "elements_chain": row["elements_chain"] or "",
                    "person_id": str(row["person_id"]) if row.get("person_id") else None,
                    "person_properties": row.get("person_properties", ""),
                    "group0_properties": row.get("group0_properties", ""),
                    "group1_properties": row.get("group1_properties", ""),
                    "group2_properties": row.get("group2_properties", ""),
                    "group3_properties": row.get("group3_properties", ""),
                    "group4_properties": row.get("group4_properties", ""),
                }

            items = []
            for instance_id, action_id, event_uuid in batch:
                clickhouse_event = events_by_uuid.get(event_uuid)
                if not clickhouse_event:
                    skipped += 1
                    continue
                items.append(
                    {
                        "clickhouse_event": clickhouse_event,
                        "action_id": action_id,
                        "instance_id": instance_id,
                    }
                )

            if not items:
                continue

            res = bulk_replay_hog_flow_invocations(
                team_id=self.team_id,
                hog_flow_id=hog_flow_id,
                items=items,
            )

            if res.status_code != 200:
                failed += len(items)
                continue

            batch_result = res.json()
            succeeded += batch_result.get("succeeded", 0)
            failed += batch_result.get("failed", 0)

        return Response({"succeeded": succeeded, "failed": failed, "skipped": skipped})

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
    serializer_class = _FallbackSerializer
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
