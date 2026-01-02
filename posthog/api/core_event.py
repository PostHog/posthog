from rest_framework import serializers, viewsets

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.core_event import CoreEvent, CoreEventCategory


class CoreEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = CoreEvent
        fields = [
            "id",
            "name",
            "description",
            "category",
            "filter",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate_category(self, value: str) -> str:
        valid_categories = [choice[0] for choice in CoreEventCategory.choices]
        if value not in valid_categories:
            raise serializers.ValidationError(f"category must be one of {valid_categories}")
        return value

    def validate_filter(self, value: dict) -> dict:
        if not value:
            raise serializers.ValidationError("filter is required")

        filter_kind = value.get("kind")
        if filter_kind not in ("EventsNode", "ActionsNode", "DataWarehouseNode"):
            raise serializers.ValidationError(f"Invalid filter kind: {filter_kind}")

        # Prevent "all events" - EventsNode must have a specific event name
        if filter_kind == "EventsNode":
            event_name = value.get("event")
            if not event_name:
                raise serializers.ValidationError("Core event cannot use 'All events'. Please select a specific event.")

        return value

    def create(self, validated_data: dict) -> CoreEvent:
        team = self.context["get_team"]()
        return CoreEvent.objects.create(team=team, **validated_data)


class CoreEventViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    """
    CRUD operations for Core Events.

    Core events are reusable event definitions that can be shared across
    Marketing analytics, Customer analytics, and Revenue analytics.
    """

    scope_object = "INTERNAL"
    queryset = CoreEvent.objects.all()
    serializer_class = CoreEventSerializer

    def safely_get_queryset(self, queryset):
        return queryset.filter(team=self.team).order_by("created_at")
