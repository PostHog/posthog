import json
from typing import Optional, cast

from django.db.models import QuerySet

import structlog
from django_filters import BaseInFilter, CharFilter, FilterSet
from django_filters.rest_framework import DjangoFilterBackend
from loginas.utils import is_impersonated_session
from rest_framework import exceptions, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.serializers import BaseSerializer

from posthog.api.app_metrics2 import AppMetricsMixin
from posthog.api.log_entries import LogEntryMixin
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.cdp.validation import HogFunctionFiltersSerializer, InputsSchemaItemSerializer, InputsSerializer
from posthog.models.activity_logging.activity_log import Detail, changes_between, log_activity
from posthog.models.hog_flow.hog_flow import HogFlow
from posthog.models.hog_function_template import HogFunctionTemplate
from posthog.plugins.plugin_server_api import create_hog_flow_invocation_test

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

    def to_internal_value(self, data):
        # Weirdly nested serializers don't get this set...
        self.initial_data = data
        return super().to_internal_value(data)

    def validate(self, data):
        trigger_is_function = False
        if data.get("type") == "trigger":
            if data.get("config", {}).get("type") in ["webhook", "tracking_pixel"]:
                trigger_is_function = True
            elif data.get("config", {}).get("type") == "event":
                filters = data.get("config", {}).get("filters", {})
                if filters:
                    serializer = HogFunctionFiltersSerializer(data=filters, context=self.context)
                    serializer.is_valid(raise_exception=True)
                    data["config"]["filters"] = serializer.validated_data
            else:
                raise serializers.ValidationError({"config": "Invalid trigger type"})

        if "function" in data.get("type", "") or trigger_is_function:
            template_id = data.get("config", {}).get("template_id", "")
            template = HogFunctionTemplate.get_template(template_id)
            if not template:
                raise serializers.ValidationError({"template_id": "Template not found"})

            input_schema = template.inputs_schema
            inputs = data.get("config", {}).get("inputs", {})

            function_config_serializer = HogFlowConfigFunctionInputsSerializer(
                data={
                    "inputs_schema": input_schema,
                    "inputs": inputs,
                },
                context={"function_type": template.type},
            )

            function_config_serializer.is_valid(raise_exception=True)

            data["config"]["inputs"] = function_config_serializer.validated_data["inputs"]

        return data


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
            "conversion",
            "exit_condition",
            "edges",
            "actions",
            "abort_action",
        ]
        read_only_fields = fields


class HogFlowSerializer(HogFlowMinimalSerializer):
    actions = serializers.ListField(child=HogFlowActionSerializer(), required=True)

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
            "conversion",
            "exit_condition",
            "edges",
            "actions",
            "abort_action",
        ]
        read_only_fields = [
            "id",
            "version",
            "created_at",
            "created_by",
            "abort_action",
        ]

    def validate(self, data):
        instance = cast(Optional[HogFlow], self.instance)
        actions = data.get("actions", instance.actions if instance else [])
        # The trigger is derived from the actions. We can trust the action level validation and pull it out
        trigger_actions = [action for action in actions if action.get("type") == "trigger"]

        if len(trigger_actions) != 1:
            raise serializers.ValidationError({"actions": "Exactly one trigger action is required"})

        data["trigger"] = trigger_actions[0]["config"]

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


class HogFlowViewSet(TeamAndOrgViewSetMixin, LogEntryMixin, AppMetricsMixin, viewsets.ModelViewSet):
    scope_object = "INTERNAL"
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
        # TODO(team-messaging): Somehow implement version lookups
        return super().safely_get_object(queryset)

    def perform_create(self, serializer):
        serializer.save()
        log_activity(
            organization_id=self.organization.id,
            team_id=self.team_id,
            user=serializer.context["request"].user,
            was_impersonated=is_impersonated_session(serializer.context["request"]),
            item_id=serializer.instance.id,
            scope="HogFlow",
            activity="created",
            detail=Detail(name=serializer.instance.name, type="standard"),
        )

    def perform_update(self, serializer):
        # TODO(team-messaging): Atomically increment version, insert new object instead of default update behavior
        instance_id = serializer.instance.id

        try:
            before_update = HogFlow.objects.get(pk=instance_id)
        except HogFlow.DoesNotExist:
            before_update = None

        serializer.save()

        changes = changes_between("HogFlow", previous=before_update, current=serializer.instance)

        log_activity(
            organization_id=self.organization.id,
            team_id=self.team_id,
            user=serializer.context["request"].user,
            was_impersonated=is_impersonated_session(serializer.context["request"]),
            item_id=instance_id,
            scope="HogFlow",
            activity="updated",
            detail=Detail(changes=changes, name=serializer.instance.name),
        )

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
