from rest_framework import filters, mixins, permissions, serializers, viewsets

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


class EventDefinitionViewSet(
    StructuredViewSetMixin, mixins.ListModelMixin, viewsets.GenericViewSet,
):
    serializer_class = EventDefinitionSerializer
    permission_classes = [permissions.IsAuthenticated, OrganizationMemberPermissions]
    lookup_field = "id"
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["name"]
    ordering_fields = ["name", "volume_30_day", "query_usage_30_day"]  # User can filter by any of these attributes
    ordering = [
        "-query_usage_30_day",
        "-volume_30_day",
        "name",
    ]  # Ordering below ensures more relevant results are returned first, particularly relevant for initial fetch

    def get_queryset(self):
        return self.filter_queryset_by_parents_lookups(EventDefinition.objects.all())
