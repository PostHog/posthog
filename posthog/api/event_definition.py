from typing import List

from django.db.models.fields import mixins
from rest_framework import serializers, viewsets

from posthog.api.routing import StructuredViewSetMixin
from posthog.models import EventDefinition, Team


class EventDefinitionSerializer(serializers.ModelSerializer):
    class Meta:
        model = EventDefinition
        fields = (
            "uuid",
            "name",
            "is_numerical",
            "volume_30_day",
            "query_usage_30_day",
        )

    def get_event_names_with_usage(self, instance: Team) -> List:
        return instance.get_latest_event_names_with_usage()


class EventDefinitionViewSet(
    StructuredViewSetMixin, mixins.ListModelMixin, viewsets.GenericViewSet,
):
    serializer_class = EventDefinitionSerializer
    queryset = EventDefinition.objects.all()
    lookup_field = "uuid"
