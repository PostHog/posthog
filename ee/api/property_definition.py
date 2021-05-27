from typing import Optional

from rest_framework import mixins, serializers, viewsets
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from ee.models.property_definition import EnterprisePropertyDefinition
from posthog.api.property_definition import PropertyDefinitionSerializer, PropertyDefinitionViewSet
from posthog.api.routing import StructuredViewSetMixin
from posthog.models.property_definition import PropertyDefinition


class EnterprisePropertyDefinitionSerializer(PropertyDefinitionSerializer):
    description = serializers.SerializerMethodField()

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
        read_only_fields = ["id", "name", "tags", "volume_30_day", "query_usage_30_day"]

        def update(
            self, property_definition: EnterprisePropertyDefinition, validated_data
        ) -> EnterprisePropertyDefinition:
            if self.context["request"].user.organization.is_feature_available("event_property_collaboration"):
                data = self.context["request"].data
                event = EnterprisePropertyDefinition.objects.update_or_create(
                    propertydefinition_ptr_id=property_definition.id, team=property_definition.team, defaults=data
                )
                return event[0]

            raise PermissionDenied("Enterprise plan feature")

        def get_description(self, property_definition: PropertyDefinition) -> Optional[str]:
            if self.context["request"].user.organization.is_feature_available("event_property_collaboration"):
                property = EnterprisePropertyDefinition.objects.filter(id=property_definition.id)
                if property.exists():
                    return property.first().description
            return None


class EnterprisePropertyDefinitionViewSet(
    StructuredViewSetMixin, mixins.ListModelMixin, mixins.UpdateModelMixin, viewsets.GenericViewSet,
):
    serializer_class = EnterprisePropertyDefinitionSerializer
    ordering = PropertyDefinitionViewSet.ordering

    def get_queryset(self):
        return self.filter_queryset_by_parents_lookups(PropertyDefinition.objects.all()).order_by(self.ordering,)

    def retrieve(self, request, **kwargs):
        id = kwargs["pk"]
        event = self.get_queryset().get(id=id)
        serializer = EnterprisePropertyDefinition(event)
        return Response(serializer.data)
