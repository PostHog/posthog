from django.db import IntegrityError
from rest_framework import mixins, serializers, status
from rest_framework.exceptions import APIException
from rest_framework.viewsets import GenericViewSet

from ee.models.assistant import CoreMemory
from posthog.api.routing import TeamAndOrgViewSetMixin


class Conflict(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "Resource already exists."
    default_code = "conflict"


class CoreMemorySerializer(serializers.ModelSerializer):
    class Meta:
        model = CoreMemory
        fields = ["id", "text"]

    def create(self, validated_data):
        try:
            validated_data["team"] = self.context["team"]
            validated_data["initial_text"] = validated_data["text"]
            validated_data["scraping_status"] = CoreMemory.ScrapingStatus.COMPLETED
            return super().create(validated_data)
        except IntegrityError:
            raise Conflict("Core memory already exists for this environment.")


class CoreMemoryViewSet(
    TeamAndOrgViewSetMixin,
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    GenericViewSet,
):
    scope_object = "INTERNAL"
    serializer_class = CoreMemorySerializer
    queryset = CoreMemory.objects.all()

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["team"] = self.team
        return context
