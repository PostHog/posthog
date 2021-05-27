from typing import Optional

from rest_framework import mixins, serializers, viewsets
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from ee.models.event_definition import EnterpriseEventDefinition
from posthog.api.event_definition import EventDefinitionSerializer, EventDefinitionViewSet
from posthog.api.routing import StructuredViewSetMixin
from posthog.models.event_definition import EventDefinition


class EnterpriseEventDefinitionSerializer(EventDefinitionSerializer):
    description = serializers.SerializerMethodField()

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
            data = self.context["request"].data
            event = EnterpriseEventDefinition.objects.update_or_create(
                eventdefinition_ptr_id=event_definition.id, team=event_definition.team, defaults=data
            )
            return event[0]

        raise PermissionDenied("Enterprise plan feature")

    def get_description(self, event_definition: EventDefinition) -> Optional[str]:
        if self.context["request"].user.organization.is_feature_available("event_property_collaboration"):
            event = EnterpriseEventDefinition.objects.filter(id=event_definition.id)
            if event.exists():
                return event.first().description
        return None


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
