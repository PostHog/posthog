import json
import uuid as uuid_mod
from typing import Optional, cast

from django.db.models import QuerySet
from django.utils import timezone

import structlog
import posthoganalytics
from django_filters import BaseInFilter, CharFilter, FilterSet
from django_filters.rest_framework import DjangoFilterBackend
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
from posthog.plugins.plugin_server_api import create_hog_flow_invocation_test

from products.workflows.backend.models.hog_flow_batch_job import HogFlowBatchJob

logger = structlog.get_logger(__name__)


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

                # Look up encrypted inputs for this specific action so the
                # InputsSerializer can validate secret fields without their
                # plaintext values being present in the draft data.
                all_encrypted = self.context.get("encrypted_inputs") or {}
                action_encrypted = all_encrypted.get(data.get("id", "")) or None

                function_config_serializer = HogFlowConfigFunctionInputsSerializer(
                    data={
                        "inputs_schema": input_schema,
                        "inputs": inputs,
                    },
                    context={"function_type": template.type, "encrypted_inputs": action_encrypted},
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
    ttl = serializers.IntegerField(required=False, min_value=60, max_value=60 * 60 * 24 * 365 * 3, allow_null=True)
    threshold = serializers.IntegerField(required=False, allow_null=True)
    hash = serializers.CharField(required=True)
    bytecode = serializers.JSONField(required=False, allow_null=True)

    def validate(self, attrs):
        attrs["bytecode"] = generate_template_bytecode(attrs["hash"], input_collector=set())

        return super().validate(attrs)


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
            "draft",
            "draft_updated_at",
        ]
        read_only_fields = fields

    def _mask_secret_inputs_in_actions(self, actions: list, encrypted_inputs: dict) -> list:
        """Replace secret input values with {"secret": True} markers in action configs."""
        trigger_type = None
        for act in actions:
            if act.get("type") == "trigger":
                trigger_type = act.get("config", {}).get("type")
                break

        for act in actions:
            action_type = act.get("type", "")
            config = act.get("config", {})
            action_id = act.get("id", "")

            is_function_action = action_type in HogFlow.FUNCTION_ACTION_TYPES
            is_function_trigger = action_type == "trigger" and trigger_type in (
                "webhook",
                "manual",
                "tracking_pixel",
                "schedule",
            )

            if not (is_function_action or is_function_trigger):
                continue

            template_id = config.get("template_id", "")
            if not template_id:
                continue

            template = HogFunctionTemplate.get_template(template_id)
            if not template or not template.inputs_schema:
                continue

            inputs = config.get("inputs", {}) or {}
            action_encrypted = encrypted_inputs.get(action_id, {}) or {}

            for schema in template.inputs_schema:
                if not schema.get("secret"):
                    continue
                key = schema.get("key", "")
                has_value = action_encrypted.get(key) or inputs.get(key)
                if has_value:
                    inputs[key] = {"secret": True}

            config["inputs"] = inputs
        return actions

    def to_representation(self, instance):
        is_model = isinstance(instance, HogFlow)
        encrypted_inputs = instance.encrypted_inputs or {} if is_model else {}
        draft_encrypted_inputs = instance.draft_encrypted_inputs or {} if is_model else {}
        data = super().to_representation(instance)

        if encrypted_inputs:
            actions = data.get("actions") or []
            if actions:
                data["actions"] = self._mask_secret_inputs_in_actions(actions, encrypted_inputs)

        # Draft actions use draft_encrypted_inputs (falling back to encrypted_inputs for unchanged actions)
        draft = data.get("draft") or {}
        draft_actions = draft.get("actions") if isinstance(draft, dict) else None
        if draft_actions:
            merged_for_draft = {**encrypted_inputs, **draft_encrypted_inputs}
            if merged_for_draft:
                draft["actions"] = self._mask_secret_inputs_in_actions(draft_actions, merged_for_draft)

        return data


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
            "draft",
            "draft_updated_at",
        ]
        read_only_fields = [
            "id",
            "version",
            "created_at",
            "created_by",
            "abort_action",
            "billable_action_types",  # Computed field, not user-editable
            "draft",
            "draft_updated_at",
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

    # Fields that represent workflow config edits (clearing draft on save)
    # name/description are metadata and don't affect the live workflow config
    CONTENT_FIELDS = {
        "trigger_masking",
        "conversion",
        "exit_condition",
        "edges",
        "actions",
        "variables",
    }

    def update(self, instance, validated_data):
        # Clear draft when content fields are saved directly (not status-only updates)
        if validated_data.keys() & self.CONTENT_FIELDS:
            validated_data["draft"] = None
            validated_data["draft_updated_at"] = None
        return super().update(instance, validated_data)


class HogFlowDraftSerializer(serializers.Serializer):
    """Accepts all editable workflow fields, all optional, for draft saves."""

    name = serializers.CharField(max_length=400, required=False)
    description = serializers.CharField(required=False, allow_blank=True)
    trigger_masking = serializers.JSONField(required=False, allow_null=True)
    conversion = serializers.JSONField(required=False, allow_null=True)
    exit_condition = serializers.CharField(max_length=100, required=False)
    edges = serializers.JSONField(required=False)
    actions = serializers.JSONField(required=False)
    variables = serializers.JSONField(required=False, allow_null=True)
    deleted_action_ids = serializers.ListField(child=serializers.CharField(), required=False)


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

    @action(detail=True, methods=["PATCH"], url_path="draft")
    def save_draft(self, request: Request, *args, **kwargs):
        hog_flow = self.get_object()

        serializer = HogFlowDraftSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        now = timezone.now()
        existing_draft = hog_flow.draft or {}
        merged_draft = {**existing_draft, **serializer.validated_data}

        update_kwargs: dict = {"draft": merged_draft, "draft_updated_at": now}
        draft_actions = merged_draft.get("actions")
        if draft_actions and isinstance(draft_actions, list):
            trigger_actions = [a for a in draft_actions if a.get("type") == "trigger"]
            draft_trigger = trigger_actions[0]["config"] if trigger_actions else hog_flow.trigger or {}

            # Extract secrets into draft_encrypted_inputs, isolated from live encrypted_inputs.
            # For secret markers, fall back to draft_encrypted_inputs first, then encrypted_inputs.
            existing_draft_encrypted = {
                **(hog_flow.encrypted_inputs or {}),
                **(hog_flow.draft_encrypted_inputs or {}),
            }
            draft_actions, new_draft_encrypted = HogFlow.extract_secret_inputs(
                draft_actions, draft_trigger, existing_draft_encrypted
            )
            merged_draft["actions"] = draft_actions
            update_kwargs["draft"] = merged_draft
            update_kwargs["draft_encrypted_inputs"] = new_draft_encrypted

        # Bypass post_save signal so draft edits don't affect live workers
        HogFlow.objects.filter(pk=hog_flow.pk).update(**update_kwargs)

        hog_flow.refresh_from_db()
        return Response(HogFlowSerializer(hog_flow, context=self.get_serializer_context()).data)

    @action(detail=True, methods=["POST"], url_path="publish")
    def publish(self, request: Request, *args, **kwargs):
        hog_flow = self.get_object()

        if not hog_flow.draft:
            raise exceptions.ValidationError("No draft to publish.")

        # Merge draft_encrypted_inputs into encrypted_inputs before publishing.
        # The draft secrets become the live secrets for actions that were edited.
        if hog_flow.draft_encrypted_inputs:
            merged = {**(hog_flow.encrypted_inputs or {}), **hog_flow.draft_encrypted_inputs}
            hog_flow.encrypted_inputs = merged if merged else None

        # Apply draft data through the full serializer with strict (active) validation
        update_data = {**hog_flow.draft}
        # Remove draft-only fields that don't belong on the workflow model
        update_data.pop("deleted_action_ids", None)
        update_data["status"] = "active"

        serializer = HogFlowSerializer(
            instance=hog_flow,
            data=update_data,
            partial=True,
            context={**self.get_serializer_context(), "encrypted_inputs": hog_flow.encrypted_inputs},
        )
        serializer.is_valid(raise_exception=True)
        # serializer.save() calls extract_secret_inputs and triggers post_save signal
        serializer.save()

        # Clear draft and draft_encrypted_inputs after successful publish
        HogFlow.objects.filter(pk=hog_flow.pk).update(draft=None, draft_updated_at=None, draft_encrypted_inputs=None)
        hog_flow.refresh_from_db()

        return Response(HogFlowSerializer(hog_flow, context=self.get_serializer_context()).data)

    @action(detail=True, methods=["POST"], url_path="discard_draft")
    def discard_draft(self, request: Request, *args, **kwargs):
        hog_flow = self.get_object()

        # Bypass post_save signal - clearing draft doesn't affect live config
        HogFlow.objects.filter(pk=hog_flow.pk).update(draft=None, draft_updated_at=None, draft_encrypted_inputs=None)

        hog_flow.refresh_from_db()
        return Response(HogFlowSerializer(hog_flow, context=self.get_serializer_context()).data)


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
