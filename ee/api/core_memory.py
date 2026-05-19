from django.db import IntegrityError

from rest_framework import mixins, serializers
from rest_framework.viewsets import GenericViewSet

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.exceptions import Conflict

from ee.models.assistant import CORE_MEMORY_MAX_CHARACTERS, CoreMemory


class MaxCoreMemorySerializer(serializers.ModelSerializer):
    class Meta:
        model = CoreMemory
        fields = ["id", "text", "scraping_status"]

    text = serializers.CharField(allow_blank=True, max_length=CORE_MEMORY_MAX_CHARACTERS)

    def create(self, validated_data):
        try:
            validated_data["team"] = self.context["get_team"]()
            validated_data["initial_text"] = validated_data["text"]
            validated_data["scraping_status"] = CoreMemory.ScrapingStatus.COMPLETED
            return super().create(validated_data)
        except IntegrityError:
            raise Conflict("Core memory already exists for this environment.")


class MaxCoreMemoryViewSet(
    TeamAndOrgViewSetMixin,
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    GenericViewSet,
):
    scope_object = "INTERNAL"
    serializer_class = MaxCoreMemorySerializer
    queryset = CoreMemory.objects.all()
