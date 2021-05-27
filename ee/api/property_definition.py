from ee.models.property_definition import EnterprisePropertyDefinition
from rest_framework import mixins, viewsets
from rest_framework.response import Response

from posthog.api.property_definition import PropertyDefinitionSerializer, PropertyDefinitionViewSet
from posthog.api.routing import StructuredViewSetMixin


class EnterprisePropertyDefinitionSerializer(PropertyDefinitionSerializer):
    class Meta:
        model = EnterprisePropertyDefinition
        fields = (
            "id",
            "name",
            "description",
            "tags",
            "volume_30_day",
            "query_usage_30_day",
        )

        def update(
            self, property_definition: EnterprisePropertyDefinition, validated_data
        ) -> EnterprisePropertyDefinition:
            response = super().update(property_definition, validated_data)
            return response


class EnterprisePropertyDefinitionViewSet(
    StructuredViewSetMixin, mixins.ListModelMixin, mixins.UpdateModelMixin, viewsets.GenericViewSet,
):
    serializer_class = EnterprisePropertyDefinitionSerializer
    ordering = PropertyDefinitionViewSet.ordering

    def get_queryset(self):
        return self.filter_queryset_by_parents_lookups(EnterprisePropertyDefinition.objects.all()).order_by(
            self.ordering,
        )

    def retrieve(self, request, **kwargs):
        id = kwargs["pk"]
        event = self.get_queryset().get(id=id)
        serializer = EnterprisePropertyDefinition(event)
        return Response(serializer.data)
