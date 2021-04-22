from typing import List

from rest_framework import filters, mixins, permissions, serializers, viewsets

from posthog.api.routing import StructuredViewSetMixin
from posthog.models import EventDefinition, Team
from posthog.permissions import OrganizationMemberPermissions


class EventDefinitionSerializer(serializers.ModelSerializer):
    class Meta:
        model = EventDefinition
        fields = (
            "uuid",
            "name",
            "volume_30_day",
            "query_usage_30_day",
        )

    def get_event_names_with_usage(self, instance: Team) -> List:
        return instance.get_latest_event_names_with_usage()


class EventDefinitionViewSet(
    StructuredViewSetMixin, mixins.ListModelMixin, viewsets.GenericViewSet,
):
    serializer_class = EventDefinitionSerializer
    permission_classes = [permissions.IsAuthenticated, OrganizationMemberPermissions]
    lookup_field = "uuid"
    ordering = "name"
    filter_backends = [filters.SearchFilter]
    search_fields = ["name"]

    def get_queryset(self):
        return self.filter_queryset_by_parents_lookups(EventDefinition.objects.all()).order_by(self.ordering)
