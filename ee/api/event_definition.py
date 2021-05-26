from rest_framework import mixins, viewsets

from ee.models import EventDefinition
from ee.models.event_definition import EnterpriseEventDefinition
from posthog.api.event_definition import EventDefinitionSerializer, EventDefinitionViewSet
from posthog.api.routing import StructuredViewSetMixin


class EnterpriseEventDefinitionSerializer(EventDefinitionSerializer):
    class Meta:
        model = EnterpriseEventDefinition
        fields = "__all__"


class EnterpriseEventDefinitionViewSet(
    StructuredViewSetMixin, mixins.ListModelMixin, mixins.UpdateModelMixin, viewsets.GenericViewSet,
):
    serializer_class = EnterpriseEventDefinitionSerializer
    ordering = EventDefinitionViewSet.ordering

    def get_queryset(self):
        return self.filter_queryset_by_parents_lookups(EventDefinition.objects.all()).order_by(self.ordering)
