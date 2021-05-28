from typing import Optional

from rest_framework import mixins, viewsets
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from ee.models.property_definition import EnterprisePropertyDefinition
from posthog.api.property_definition import PropertyDefinitionSerializer, PropertyDefinitionViewSet
from posthog.api.routing import StructuredViewSetMixin
from posthog.models.property_definition import PropertyDefinition
from itertools import chain

class EnterprisePropertyDefinitionSerializer(PropertyDefinitionSerializer):
    # description = serializers.SerializerMethodField()

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

    def update(self, property_definition: PropertyDefinition, validated_data):
        if self.context["request"].user.organization.is_feature_available("event_property_collaboration"):
            ee_propertydef = EnterprisePropertyDefinition.objects.filter(id=property_definition.id).first()
            # update if the enterprise definition exists
            if ee_propertydef:
                return super().update(ee_propertydef, validated_data)

            # create a subclass instance copy if it does not
            new_property_def = EnterprisePropertyDefinition(propertydefinition_ptr_id=property_definition.pk)
            new_property_def.__dict__.update(property_definition.__dict__)
            new_property_def.save()
            return super().update(new_property_def, validated_data)

        raise PermissionDenied("Enterprise plan feature")

        # def get_description(self, property_definition: PropertyDefinition) -> Optional[str]:
        #     if self.context["request"].user.organization.is_feature_available("event_property_collaboration"):
        #         property = EnterprisePropertyDefinition.objects.filter(id=property_definition.id)
        #         if property.exists():
        #             return property.first().description
        #     return None


class EnterprisePropertyDefinitionViewSet(
    StructuredViewSetMixin, mixins.ListModelMixin, mixins.UpdateModelMixin, viewsets.GenericViewSet,
):
    serializer_class = EnterprisePropertyDefinitionSerializer
    ordering = PropertyDefinitionViewSet.ordering

    def get_queryset(self):
        return self.filter_queryset_by_parents_lookups(PropertyDefinition.objects.all()).order_by(self.ordering)

    def get(self, request, **kwargs):
        id = kwargs["pk"]
        ee_propertydef = EnterprisePropertyDefinition.objects.filter(id=id).first()

        if ee_propertydef:
            return Response(EnterprisePropertyDefinitionSerializer(ee_propertydef).data)
        # downcast a new enterprise subclass instance with the original property definition's values
        property_def = PropertyDefinition.objects.get(id=id)
        new_property_def = EnterprisePropertyDefinition(propertydefinition_ptr_id=property_def.pk)
        new_property_def.__dict__.update(property_def.__dict__)
        new_property_def.save()
        return Response(EnterprisePropertyDefinitionSerializer(new_property_def).data)

