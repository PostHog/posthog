from rest_framework import filters, mixins, permissions, serializers, viewsets
from rest_framework.response import Response

from posthog.api.routing import StructuredViewSetMixin
from posthog.models import EventDefinition
from posthog.permissions import OrganizationMemberPermissions


class EventDefinitionSerializer(serializers.ModelSerializer):
    class Meta:
        model = EventDefinition
        fields = (
            "id",
            "name",
            "volume_30_day",
            "query_usage_30_day",
        )

    def update(self, event_definition: EventDefinition, validated_data, **kwargs) -> EventDefinition:
        response = super().update(event_definition, validated_data)
        return response


class EventDefinitionViewSet(
    StructuredViewSetMixin, mixins.ListModelMixin, mixins.UpdateModelMixin, viewsets.GenericViewSet,
):
    serializer_class = EventDefinitionSerializer
    permission_classes = [permissions.IsAuthenticated, OrganizationMemberPermissions]
    lookup_field = "id"
    ordering = "name"
    filter_backends = [filters.SearchFilter]
    search_fields = ["name"]
    queryset = EventDefinition.objects.all()

    def get_queryset(self):
        return self.filter_queryset_by_parents_lookups(EventDefinition.objects.all()).order_by(self.ordering)

    def retrieve(self, request, **kwargs):
        id = kwargs["id"]
        event = self.get_queryset().get(id=id)
        serializer = EventDefinitionSerializer(event)
        return Response(serializer.data)
