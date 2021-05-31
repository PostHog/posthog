from typing import Any, Type

from rest_framework import filters, mixins, permissions, response, serializers, viewsets
from rest_framework.exceptions import PermissionDenied
from rest_framework.request import Request

from posthog.api.routing import StructuredViewSetMixin
from posthog.models import PropertyDefinition
from posthog.permissions import OrganizationMemberPermissions


class PropertyDefinitionSerializer(serializers.ModelSerializer):
    class Meta:
        model = PropertyDefinition
        fields = (
            "id",
            "name",
            "is_numerical",
            "query_usage_30_day",
        )


class PropertyDefinitionViewSet(
    StructuredViewSetMixin, mixins.ListModelMixin, mixins.UpdateModelMixin, viewsets.GenericViewSet,
):
    serializer_class = PropertyDefinitionSerializer
    permission_classes = [permissions.IsAuthenticated, OrganizationMemberPermissions]
    lookup_field = "id"
    ordering = "name"
    filter_backends = [filters.SearchFilter]
    search_fields = ["name"]

    def get_queryset(self):
        if self.request.user.organization.is_feature_available("event_property_collaboration"):
            from ee.models.property_definition import EnterprisePropertyDefinition

            return self.filter_queryset_by_parents_lookups(EnterprisePropertyDefinition.objects.all()).order_by(
                self.ordering
            )
        return self.filter_queryset_by_parents_lookups(PropertyDefinition.objects.all()).order_by(self.ordering)

    def get_serializer_class(self) -> Type[serializers.ModelSerializer]:
        serializer_class = self.serializer_class
        if self.request.user.organization.is_feature_available("event_property_collaboration"):
            from ee.api.enterprise_property_definition import EnterprisePropertyDefinitionSerializer

            serializer_class = EnterprisePropertyDefinitionSerializer
        return serializer_class

    def retrieve(self, request: Request, *args: Any, **kwargs: Any):
        if self.request.user.organization.is_feature_available("event_property_collaboration"):
            from ee.api.enterprise_property_definition import EnterprisePropertyDefinitionSerializer

            return response.Response(
                EnterprisePropertyDefinitionSerializer(self.get_queryset().get(id=kwargs["id"])).data
            )
        raise PermissionDenied("This is an Enterprise plan feature.")
