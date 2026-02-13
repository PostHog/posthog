import re

from rest_framework import serializers, viewsets
from rest_framework.exceptions import ValidationError

from posthog.schema import (
    QuickFilterContext as QuickFilterContextEnum,
    QuickFilterType,
)

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.quick_filter import QuickFilter, QuickFilterContext


class QuickFilterSerializer(serializers.ModelSerializer):
    contexts = serializers.SerializerMethodField()
    name = serializers.CharField(allow_blank=False, trim_whitespace=True, max_length=200)
    property_name = serializers.CharField(allow_blank=False, trim_whitespace=True, max_length=500)

    class Meta:
        model = QuickFilter
        fields = [
            "id",
            "name",
            "property_name",
            "type",
            "options",
            "contexts",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "created_at",
            "updated_at",
        ]

    def get_contexts(self, obj):
        return list(obj.context_memberships.values_list("context", flat=True))

    def validate(self, attrs: dict) -> dict:
        filter_type = attrs.get("type", self.instance.type if self.instance else QuickFilterType.MANUAL_OPTIONS.value)
        options = attrs.get("options")

        if options is not None:
            if filter_type == QuickFilterType.AUTO_DISCOVERY.value:
                self._validate_auto_discovery_options(options)
            else:
                self._validate_manual_options(options)

        return attrs

    def _validate_manual_options(self, value: object) -> None:
        if not isinstance(value, list):
            raise ValidationError({"options": "Options must be a list"})

        if len(value) == 0:
            raise ValidationError({"options": "Options must contain at least one item"})

        for option in value:
            if not isinstance(option, dict):
                raise ValidationError(
                    {"options": "Each option must be an object with 'id', 'value', 'label', and 'operator' fields"}
                )
            if "id" not in option or "value" not in option or "label" not in option or "operator" not in option:
                raise ValidationError(
                    {"options": "Each option must have 'id', 'value', 'label', and 'operator' fields"}
                )

            if not isinstance(option["id"], str):
                raise ValidationError({"options": "Option 'id' must be a string"})

            opt_value = option["value"]
            if opt_value is not None:
                if isinstance(opt_value, list):
                    if not all(isinstance(v, str) for v in opt_value):
                        raise ValidationError({"options": "Option 'value' array must contain only strings"})
                elif not isinstance(opt_value, str):
                    raise ValidationError({"options": "Option 'value' must be a string, array of strings, or null"})

            if not isinstance(option["label"], str) or not isinstance(option["operator"], str):
                raise ValidationError({"options": "Option 'label' and 'operator' must be strings"})

    def _validate_auto_discovery_options(self, value: object) -> None:
        if not isinstance(value, dict):
            raise ValidationError({"options": "Options for auto-discovery must be a configuration object"})

        if "operator" not in value or not isinstance(value["operator"], str):
            raise ValidationError({"options": "Auto-discovery config must have a string 'operator' field"})

        value_pattern = value.get("value_pattern")
        if value_pattern is not None:
            if not isinstance(value_pattern, str):
                raise ValidationError({"options": "'value_pattern' must be a string"})
            if value_pattern:
                try:
                    re.compile(value_pattern)
                except re.error:
                    raise ValidationError({"options": "Invalid regex pattern in 'value_pattern'"})

    def validate_contexts(self, value):
        if not isinstance(value, list):
            raise ValidationError("Contexts must be a list")

        if len(value) == 0:
            raise ValidationError("At least one context must be specified")

        valid_contexts = [c.value for c in QuickFilterContextEnum]
        for context in value:
            if context not in valid_contexts:
                raise ValidationError(f"Invalid context '{context}'. Must be one of: {', '.join(valid_contexts)}")

        return value

    def create(self, validated_data):
        contexts = self.initial_data.get("contexts", [])

        self.validate_contexts(contexts)

        validated_data["team_id"] = self.context["team_id"]
        quick_filter = QuickFilter.objects.create(**validated_data)

        for context in contexts:
            QuickFilterContext.objects.create(
                team_id=self.context["team_id"], quick_filter=quick_filter, context=context
            )

        return quick_filter

    def update(self, instance, validated_data):
        contexts = self.initial_data.get("contexts")

        instance.name = validated_data.get("name", instance.name)
        instance.property_name = validated_data.get("property_name", instance.property_name)
        instance.type = validated_data.get("type", instance.type)
        instance.options = validated_data.get("options", instance.options)
        instance.save()

        if contexts is not None:
            self.validate_contexts(contexts)

            existing_memberships = instance.context_memberships.all()
            existing_contexts = set(existing_memberships.values_list("context", flat=True))
            new_contexts = set(contexts)

            contexts_to_remove = existing_contexts - new_contexts
            if contexts_to_remove:
                existing_memberships.filter(context__in=contexts_to_remove).delete()

            contexts_to_add = new_contexts - existing_contexts
            for context in contexts_to_add:
                QuickFilterContext.objects.create(
                    team_id=self.context["team_id"], quick_filter=instance, context=context
                )

        return instance


class QuickFilterViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "INTERNAL"
    queryset = QuickFilter.objects.all()
    serializer_class = QuickFilterSerializer

    def safely_get_queryset(self, queryset):
        queryset = queryset.filter(team=self.team).prefetch_related("context_memberships")
        context = self.request.query_params.get("context")
        if context:
            queryset = queryset.filter(context_memberships__context=context).distinct()
        return queryset.order_by("-created_at")
