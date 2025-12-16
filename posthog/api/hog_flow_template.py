from typing import Optional, cast

from django.db.models import QuerySet

import structlog
from loginas.utils import is_impersonated_session
from rest_framework import serializers, viewsets

from posthog.api.log_entries import LogEntryMixin
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.cdp.validation import HogFunctionFiltersSerializer
from posthog.models.activity_logging.activity_log import Detail, log_activity
from posthog.models.hog_flow.hog_flow_template import HogFlowTemplate
from posthog.models.hog_function_template import HogFunctionTemplate

logger = structlog.get_logger(__name__)


def _get_default_inputs_for_template(template: HogFunctionTemplate) -> dict:
    """Get default inputs for a template"""
    default_inputs = {}
    for schema_item in template.inputs_schema or []:
        if schema_item.get("default") is not None:
            default_inputs[schema_item["key"]] = {"value": schema_item["default"]}
    return default_inputs


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

        # For templates, we skip the input validation since we allow default/empty values
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
    trigger_masking = serializers.DictField(required=False, allow_null=True)
    variables = serializers.ListField(
        child=serializers.DictField(child=serializers.CharField(allow_blank=True)),
        required=False,
        allow_empty=True,
    )

    class Meta:
        model = HogFlowTemplate
        fields = [
            "id",
            "name",
            "description",
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
        actions = data.get("actions", instance.actions if instance else [])

        # Validate actions using our custom serializer (which skips input validation)
        for action_data in actions:
            serializer = HogFlowTemplateActionSerializer(data=action_data, context=self.context)
            serializer.is_valid(raise_exception=True)

        # The trigger is derived from the actions
        trigger_actions = [action for action in actions if action.get("type") == "trigger"]
        if len(trigger_actions) != 1:
            raise serializers.ValidationError({"actions": "Exactly one trigger action is required"})
        data["trigger"] = trigger_actions[0]["config"]

        # Remove metadata fields that shouldn't be in templates
        data.pop("id", None)
        data.pop("team_id", None)
        data.pop("created_at", None)
        data.pop("updated_at", None)
        data.pop("status", None)

        # Reset function action inputs to defaults from templates
        for action in actions:
            action_type = action.get("type", "")
            config = action.get("config", {})

            # Check if this is a function action or trigger function
            is_function_action = "function" in action_type
            is_trigger_function = action_type == "trigger" and config.get("type") in [
                "webhook",
                "manual",
                "tracking_pixel",
                "schedule",
            ]

            if is_function_action or is_trigger_function:
                template_id = config.get("template_id")
                if template_id:
                    template = HogFunctionTemplate.get_template(template_id)
                    if template:
                        # Reset inputs to defaults from the template
                        default_inputs = _get_default_inputs_for_template(template)
                        config["inputs"] = default_inputs

        return data

    def create(self, validated_data: dict, *args, **kwargs) -> HogFlowTemplate:
        request = self.context["request"]
        team_id = self.context["team_id"]
        validated_data["created_by"] = request.user
        validated_data["team_id"] = team_id

        return super().create(validated_data=validated_data)


class HogFlowTemplateViewSet(TeamAndOrgViewSetMixin, LogEntryMixin, viewsets.ModelViewSet):
    """
    ViewSet for hog flow templates.
    Templates can be used to create new hog flows.
    """

    scope_object = "INTERNAL"
    queryset = HogFlowTemplate.objects.all()
    serializer_class = HogFlowTemplateSerializer
    log_source = "hog_flow_template"
    http_method_names = ["get", "post", "put", "patch", "delete", "head", "options"]

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        if self.action == "list":
            queryset = queryset.order_by("-updated_at")

        return queryset

    def perform_create(self, serializer):
        serializer.save()
        logger.info(
            "hog_flow_template_created",
            template_id=str(serializer.instance.id),
            template_name=serializer.instance.name,
            team_id=self.team_id,
        )
        log_activity(
            organization_id=self.organization.id,
            team_id=self.team_id,
            user=serializer.context["request"].user,
            was_impersonated=is_impersonated_session(serializer.context["request"]),
            item_id=serializer.instance.id,
            scope="HogFlow",
            activity="created",
            detail=Detail(name=serializer.instance.name, type="template"),
        )

        # TODOdin: Add posthoganalytics.capture(...)
