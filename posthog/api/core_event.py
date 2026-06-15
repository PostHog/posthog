from rest_framework import serializers, viewsets

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.core_event import CoreEvent


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
