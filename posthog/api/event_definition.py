from rest_framework import filters, mixins, permissions, serializers, viewsets

from posthog.api.routing import StructuredViewSetMixin
from posthog.filters import FuzzySearchFilterBackend
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
    ordering = "name"
    filter_backends = [FuzzySearchFilterBackend]
    search_field = "name"
    search_threshold = 0.15

    def get_queryset(self):
        return self.filter_queryset_by_parents_lookups(EventDefinition.objects.all())
