from typing import Optional, cast

from django.db.models import Q

import structlog
import posthoganalytics
from loginas.utils import is_impersonated_session
from rest_framework import serializers, viewsets
from rest_framework.permissions import SAFE_METHODS, BasePermission
from rest_framework.request import Request

from posthog.api.hog_flow import HogFlowMaskingSerializer, HogFlowVariableSerializer
from posthog.api.log_entries import LogEntryMixin
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.cdp.validation import HogFunctionFiltersSerializer
from posthog.models import User
from posthog.models.activity_logging.activity_log import Detail, log_activity
from posthog.models.hog_flow.hog_flow_template import HogFlowTemplate
from posthog.models.hog_function_template import HogFunctionTemplate
from posthog.permissions import get_organization_from_view

logger = structlog.get_logger(__name__)


class OnlyStaffCanEditGlobalHogFlowTemplate(BasePermission):
    message = "You don't have edit permissions for global workflow templates."

    def _has_feature_flag(self, request: Request, view) -> bool:
        """Check if user has the workflows-template-creation feature flag"""
        try:
            organization = get_organization_from_view(view)
            user = cast(User, request.user)
            return user.distinct_id is not None and posthoganalytics.feature_enabled(
                "workflows-template-creation",
                user.distinct_id,
                groups={"organization": str(organization.id)},
                group_properties={"organization": {"id": str(organization.id)}},
                only_evaluate_locally=False,
                send_feature_flag_events=False,
            )
        except (ValueError, AttributeError):
            return False

    def has_permission(self, request: Request, view) -> bool:
        if request.method in SAFE_METHODS:
            return True

        if not self._has_feature_flag(request, view):
            return False

        if request.method == "POST":
            scope = request.data.get("scope")
            if scope == HogFlowTemplate.Scope.GLOBAL:
                return request.user.is_staff

        return True

    def has_object_permission(self, request: Request, view, obj: HogFlowTemplate) -> bool:
        if request.method in SAFE_METHODS:
            return True

        # Prevent non-staff from editing global templates / updating team template to global
        if obj.scope == HogFlowTemplate.Scope.GLOBAL or request.data.get("scope") == HogFlowTemplate.Scope.GLOBAL:
            return request.user.is_staff

        return True


class HogFlowTemplateActionSerializer(serializers.Serializer):
    """
    Custom action serializer for templates that skips input validation
    (since templates should have default/empty values).
    """

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
        self.initial_data = data
        return super().to_internal_value(data)

    def validate(self, data):
        trigger_is_function = False
        if data.get("type") == "trigger":
            if data.get("config", {}).get("type") in ["webhook", "manual", "tracking_pixel", "schedule"]:
                trigger_is_function = True
            elif data.get("config", {}).get("type") == "event":
                filters = data.get("config", {}).get("filters", {})
                if filters:
                    serializer = HogFunctionFiltersSerializer(data=filters, context=self.context)
                    serializer.is_valid(raise_exception=True)
                    data["config"]["filters"] = serializer.validated_data
            else:
                raise serializers.ValidationError({"config": "Invalid trigger type"})

        # For templates, we skip the input validation since we allow default/empty values and reset inputs anyway
        # Instead, we just verify the template exists
        if "function" in data.get("type", "") or trigger_is_function:
            template_id = data.get("config", {}).get("template_id", "")
            template = HogFunctionTemplate.get_template(template_id)
            if not template:
                raise serializers.ValidationError({"template_id": "Template not found"})

        conditions = data.get("config", {}).get("conditions", [])
        single_condition = data.get("config", {}).get("condition", None)
        if conditions and single_condition:
            raise serializers.ValidationError({"config": "Cannot specify both 'conditions' and 'condition' fields"})
        if single_condition:
            conditions = [single_condition]

        if conditions:
            for condition in conditions:
                filters = condition.get("filters")
                if filters is not None:
                    if "events" in filters:
                        raise serializers.ValidationError("Event filters are not allowed in conditionals")

                    serializer = HogFunctionFiltersSerializer(data=filters, context=self.context)
                    serializer.is_valid(raise_exception=True)
                    condition["filters"] = serializer.validated_data

        return data


class HogFlowTemplateSerializer(serializers.ModelSerializer):
    """
    Serializer for creating hog flow templates.
    Validates and sanitizes the workflow before creating it as a template.
    """

    created_by = serializers.SerializerMethodField()
    actions = serializers.ListField(child=HogFlowTemplateActionSerializer(), required=True)
    trigger_masking = HogFlowMaskingSerializer(required=False, allow_null=True)
    variables = HogFlowVariableSerializer(required=False)

    class Meta:
        model = HogFlowTemplate
        fields = [
            "id",
            "name",
            "description",
            "image_url",
            "scope",
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
        ]
        read_only_fields = ["id", "created_at", "updated_at", "created_by"]

    def get_created_by(self, obj):
        if obj.created_by:
            from posthog.api.shared import UserBasicSerializer

            return UserBasicSerializer(obj.created_by).data
        return None

    def validate(self, data):
        instance = cast(Optional[HogFlowTemplate], self.instance)

        name = data.get("name")
        if name is None:
            if not instance or not instance.name:
                raise serializers.ValidationError({"name": "Name is required"})
        elif not name.strip():
            raise serializers.ValidationError({"name": "Name cannot be empty"})

        actions = data.get("actions", instance.actions if instance else [])

        # Validate actions using our custom serializer (which skips input validation)
        for action_data in actions:
            serializer = HogFlowTemplateActionSerializer(data=action_data, context=self.context)
            serializer.is_valid(raise_exception=True)

        trigger_actions = [action for action in actions if action.get("type") == "trigger"]
        if len(trigger_actions) != 1:
            raise serializers.ValidationError({"actions": "Exactly one trigger action is required"})
        data["trigger"] = trigger_actions[0]["config"]

        data.pop("id", None)
        data.pop("team_id", None)
        data.pop("created_at", None)
        data.pop("updated_at", None)
        data.pop("created_by", None)
        data.pop("status", None)
        data.pop("version", None)

        return data

    def create(self, validated_data: dict, *args, **kwargs) -> HogFlowTemplate:
        request = self.context["request"]
        team_id = self.context["team_id"]
        validated_data["created_by"] = request.user
        validated_data["team_id"] = team_id
        # Ensure scope is always set (defaults to 'team' if not provided)
        if not validated_data.get("scope"):
            validated_data["scope"] = HogFlowTemplate.Scope.ONLY_TEAM

        return super().create(validated_data=validated_data)


class HogFlowTemplateViewSet(TeamAndOrgViewSetMixin, LogEntryMixin, viewsets.ModelViewSet):
    scope_object = "INTERNAL"
    queryset = HogFlowTemplate.objects.all()
    serializer_class = HogFlowTemplateSerializer
    permission_classes = [OnlyStaffCanEditGlobalHogFlowTemplate]
    log_source = "hog_flow_template"
    app_source = "hog_flow_template"
    http_method_names = ["get", "post", "put", "patch", "delete", "head", "options"]

    def dangerously_get_queryset(self):
        # NOTE: we use the dangerous version as we want to bypass the team/org scoping and do it here instead depending on the scope
        # Return global templates OR templates that match the current team
        query_condition = Q(team_id=self.team_id) | Q(scope=HogFlowTemplate.Scope.GLOBAL)

        qs = HogFlowTemplate.objects.filter(query_condition)

        if self.action == "list":
            qs = qs.order_by("-updated_at")

        return qs

    def perform_create(self, serializer):
        serializer.save()
        log_activity(
            organization_id=self.organization.id,
            team_id=self.team_id,
            user=serializer.context["request"].user,
            was_impersonated=is_impersonated_session(serializer.context["request"]),
            item_id=serializer.instance.id,
            scope="HogFlowTemplate",
            activity="created",
            detail=Detail(name=serializer.instance.name, type="standard"),
        )

        try:
            edges_count = len(serializer.instance.edges) if serializer.instance.edges else 0
            actions_count = len(serializer.instance.actions) if serializer.instance.actions else 0

            posthoganalytics.capture(
                distinct_id=str(serializer.context["request"].user.distinct_id),
                event="hog_flow_template_created",
                properties={
                    "workflow_template_id": str(serializer.instance.id),
                    "workflow_template_name": serializer.instance.name,
                    "edges_count": edges_count,
                    "actions_count": actions_count,
                    "team_id": str(self.team_id),
                    "organization_id": str(self.organization.id),
                    "scope": serializer.instance.scope if serializer.instance else None,
                },
            )
        except Exception as e:
            logger.warning("Failed to capture hog_flow_template_created event", error=str(e))

    def perform_update(self, serializer):
        serializer.validated_data["team_id"] = self.team_id
        log_activity(
            organization_id=self.organization.id,
            team_id=self.team_id,
            user=serializer.context["request"].user,
            was_impersonated=is_impersonated_session(self.request),
            item_id=serializer.instance.id,
            scope="HogFlowTemplate",
            activity="updated",
            detail=Detail(name=serializer.instance.name, type="standard"),
        )
        serializer.save()

    def perform_destroy(self, instance: HogFlowTemplate):
        # Authentication is enforced, so user cannot be AnonymousUser
        user = cast(User, self.request.user)
        log_activity(
            organization_id=self.organization.id,
            team_id=self.team_id,
            user=user,
            was_impersonated=is_impersonated_session(self.request),
            item_id=instance.id,
            scope="HogFlowTemplate",
            activity="deleted",
            detail=Detail(name=instance.name, type="standard"),
        )

        super().perform_destroy(instance)
