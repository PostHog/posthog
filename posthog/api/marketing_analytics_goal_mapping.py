from rest_framework import serializers, viewsets

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.core_event import CoreEvent
from posthog.models.marketing_analytics_goal_mapping import MarketingAnalyticsGoalMapping


class MarketingAnalyticsGoalMappingSerializer(serializers.ModelSerializer):
    # Accept core_event_id for write operations, return full core_event for reads
    core_event_id = serializers.UUIDField(write_only=True)

    class Meta:
        model = MarketingAnalyticsGoalMapping
        fields = [
            "id",
            "core_event",
            "core_event_id",
            "schema_map",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "core_event", "created_at", "updated_at"]
        depth = 1  # Include nested core_event data in responses

    def validate_core_event_id(self, value):
        team = self.context["get_team"]()
        try:
            CoreEvent.objects.get(id=value, team=team)
        except CoreEvent.DoesNotExist:
            raise serializers.ValidationError("Core event not found")
        return value

    def validate(self, attrs: dict) -> dict:
        core_event_id = attrs.get("core_event_id")
        schema_map = attrs.get("schema_map", {})

        if core_event_id:
            team = self.context["get_team"]()
            try:
                core_event = CoreEvent.objects.get(id=core_event_id, team=team)
                # For DataWarehouseNode, schema_map is required with UTM fields
                if core_event.filter.get("kind") == "DataWarehouseNode":
                    if not schema_map:
                        raise serializers.ValidationError(
                            "schema_map is required for DataWarehouseNode goals. "
                            "Please specify utm_campaign_name and utm_source_name field mappings."
                        )
                    if "utm_campaign_name" not in schema_map:
                        raise serializers.ValidationError(
                            "schema_map must include 'utm_campaign_name' for DataWarehouseNode goals"
                        )
                    if "utm_source_name" not in schema_map:
                        raise serializers.ValidationError(
                            "schema_map must include 'utm_source_name' for DataWarehouseNode goals"
                        )
            except CoreEvent.DoesNotExist:
                pass  # Already handled in validate_core_event_id

        return attrs

    def create(self, validated_data: dict) -> MarketingAnalyticsGoalMapping:
        team = self.context["get_team"]()
        core_event_id = validated_data.pop("core_event_id")
        core_event = CoreEvent.objects.get(id=core_event_id, team=team)
        return MarketingAnalyticsGoalMapping.objects.create(team=team, core_event=core_event, **validated_data)

    def update(self, instance, validated_data):
        # Only schema_map can be updated, core_event cannot be changed
        validated_data.pop("core_event_id", None)
        return super().update(instance, validated_data)


class MarketingAnalyticsGoalMappingViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    """
    CRUD operations for Marketing Analytics goal mappings.

    These mappings connect CoreEvents to Marketing Analytics
    with optional UTM field mappings for data warehouse goals.
    """

    scope_object = "INTERNAL"
    queryset = MarketingAnalyticsGoalMapping.objects.all()
    serializer_class = MarketingAnalyticsGoalMappingSerializer

    def safely_get_queryset(self, queryset):
        return queryset.filter(team=self.team).select_related("core_event").order_by("created_at")
