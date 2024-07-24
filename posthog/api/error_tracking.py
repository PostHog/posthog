from django.db.models import QuerySet
from rest_framework import serializers, viewsets

from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.error_tracking import ErrorTrackingGroup


class ErrorTrackingGroupSerializer(serializers.ModelSerializer):
    class Meta:
        model = ErrorTrackingGroup
        fields = ["assignee"]


class ErrorTrackingGroupViewSet(TeamAndOrgViewSetMixin, ForbidDestroyModel, viewsets.ModelViewSet):
    scope_object = "INTERNAL"
    queryset = ErrorTrackingGroup.objects.all()
    serializer_class = ErrorTrackingGroupSerializer

    def safely_get_object(self, queryset) -> QuerySet:
        fingerprint = self.kwargs["pk"]
        group, _ = queryset.get_or_create(fingerprint=fingerprint, team=self.team)
        return group
