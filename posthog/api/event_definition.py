from typing import Any, Type

from rest_framework import filters, mixins, permissions, response, serializers, viewsets
from rest_framework.exceptions import PermissionDenied
from rest_framework.request import Request

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

    def update(self, event_definition: EventDefinition, validated_data):
        raise PermissionDenied("This is an Enterprise plan feature.")


class EventDefinitionViewSet(
    StructuredViewSetMixin, mixins.ListModelMixin, mixins.UpdateModelMixin, viewsets.GenericViewSet,
):
    serializer_class = EventDefinitionSerializer
    permission_classes = [permissions.IsAuthenticated, OrganizationMemberPermissions]
    lookup_field = "id"
    ordering = "name"
    filter_backends = [filters.SearchFilter]
    search_fields = ["name"]

    def get_queryset(self):
        if self.request.user.organization.is_feature_available("event_property_collaboration"):
            from ee.models.event_definition import EnterpriseEventDefinition

            return self.filter_queryset_by_parents_lookups(EnterpriseEventDefinition.objects.all()).order_by(
                self.ordering
            )
        return self.filter_queryset_by_parents_lookups(EventDefinition.objects.all()).order_by(self.ordering)

    def get_serializer_class(self) -> Type[serializers.ModelSerializer]:
        serializer_class = self.serializer_class
        if self.request.user.organization.is_feature_available("event_property_collaboration"):
            from ee.api.enterprise_event_definition import EnterpriseEventDefinitionSerializer

            serializer_class = EnterpriseEventDefinitionSerializer
        return serializer_class

    def retrieve(self, request: Request, *args: Any, **kwargs: Any):
        if self.request.user.organization.is_feature_available("event_property_collaboration"):
            from ee.api.enterprise_event_definition import EnterpriseEventDefinitionSerializer

            return response.Response(EnterpriseEventDefinitionSerializer(self.get_queryset().get(id=kwargs["id"])).data)
        raise PermissionDenied("This is an Enterprise plan feature.")
