from rest_framework import mixins, viewsets
from rest_framework.response import Response

from ee.models.event_definition import EnterpriseEventDefinition
from posthog.api.event_definition import EventDefinitionSerializer, EventDefinitionViewSet
from posthog.api.routing import StructuredViewSetMixin


class EnterpriseEventDefinitionSerializer(EventDefinitionSerializer):
    class Meta:
        model = EnterpriseEventDefinition
        fields = (
            "id",
            "name",
            "owner",
            "description",
            "tags",
            "volume_30_day",
            "query_usage_30_day",
        )

    def update(
        self, event_definition: EnterpriseEventDefinition, validated_data, **kwargs,
    ) -> EnterpriseEventDefinition:
        response = super().update(event_definition, validated_data)
        return response


class EnterpriseEventDefinitionViewSet(
    StructuredViewSetMixin, mixins.ListModelMixin, mixins.UpdateModelMixin, viewsets.GenericViewSet,
):
    serializer_class = EnterpriseEventDefinitionSerializer
    ordering = EventDefinitionViewSet.ordering

    def get_queryset(self):
        return self.filter_queryset_by_parents_lookups(EnterpriseEventDefinition.objects.all()).order_by(self.ordering)

    def retrieve(self, request, **kwargs):
        id = kwargs["pk"]
        event = self.get_queryset().get(id=id)
        serializer = EnterpriseEventDefinitionSerializer(event)
        return Response(serializer.data)
