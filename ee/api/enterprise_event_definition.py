from typing import Optional

from rest_framework import mixins, serializers, viewsets
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from ee.models.event_definition import EnterpriseEventDefinition
from posthog.api.event_definition import EventDefinitionSerializer, EventDefinitionViewSet
from posthog.api.routing import StructuredViewSetMixin
from posthog.models.event_definition import EventDefinition


class EnterpriseEventDefinitionSerializer(EventDefinitionSerializer):
    # description = serializers.SerializerMethodField()

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
        read_only_fields = ["id", "name", "owner", "tags", "volume_30_day", "query_usage_30_day"]

    def update(self, event_definition: EventDefinition, validated_data, **kwargs,) -> EnterpriseEventDefinition:
        if self.context["request"].user.organization.is_feature_available("event_property_collaboration"):
            ee_eventdef = EnterpriseEventDefinition.objects.filter(id=event_definition.id).first()
            # update if the enterprise definition exists
            if ee_eventdef:
                return super().update(ee_eventdef, validated_data)

            # create a subclass instance copy if it does not
            new_event_def = EnterpriseEventDefinition(propertydefinition_ptr_id=event_definition.pk)
            new_event_def.__dict__.update(event_definition.__dict__)
            new_event_def.save()
            return super().update(new_event_def, validated_data)

    # def get_description(self, event_definition: EventDefinition) -> Optional[str]:
    #     if self.context["request"].user.organization.is_feature_available("event_property_collaboration"):
    #         event = EnterpriseEventDefinition.objects.filter(id=event_definition.id)
    #         if event.exists():
    #             return event.first().description
    #     return None


class EnterpriseEventDefinitionViewSet(
    StructuredViewSetMixin, mixins.ListModelMixin, mixins.UpdateModelMixin, viewsets.GenericViewSet,
):
    serializer_class = EnterpriseEventDefinitionSerializer
    ordering = EventDefinitionViewSet.ordering

    def get_queryset(self):
        return self.filter_queryset_by_parents_lookups(EnterpriseEventDefinition.objects.all()).order_by(self.ordering)

    def get(self, request, **kwargs):
        id = kwargs["pk"]
        ee_eventdef = EnterpriseEventDefinition.objects.filter(id=id).first()

        if ee_eventdef:
            return Response(EnterpriseEventDefinitionSerializer(ee_eventdef).data)
        # downcast a new enterprise subclass instance with the original property definition's values
        event_def = EventDefinition.objects.get(id=id)
        new_event_def = EnterpriseEventDefinition(eventdefinition_ptr_id=event_def.pk)
        new_event_def.__dict__.update(event_def.__dict__)
        new_event_def.save()
        return Response(EnterpriseEventDefinitionSerializer(new_event_def).data)
