from rest_framework import mixins, viewsets

from ee.models.property_definition import EnterprisePropertyDefinition
from posthog.api.property_definition import PropertyDefinitionSerializer, PropertyDefinitionViewSet
from posthog.api.routing import StructuredViewSetMixin
from posthog.models.property_definition import PropertyDefinition


class EnterprisePropertyDefinitionSerializer(PropertyDefinitionSerializer):
    class Meta:
        model = EnterprisePropertyDefinition
        fields = "__all__"


class EnterprisePropertyDefinitionViewSet(
    StructuredViewSetMixin, mixins.ListModelMixin, mixins.UpdateModelMixin, viewsets.GenericViewSet,
):
    serializer_class = EnterprisePropertyDefinitionSerializer
    ordering = PropertyDefinitionViewSet.ordering

    def get_queryset(self):
        return self.filter_queryset_by_parents_lookups(PropertyDefinition.objects.all()).order_by(self.ordering)
