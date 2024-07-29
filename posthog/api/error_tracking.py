from django.db.models import QuerySet
from rest_framework import serializers, viewsets

from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.error_tracking import ErrorTrackingGroup
from rest_framework.decorators import action
from rest_framework.response import Response


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

    @action(methods=["POST"], detail=True)
    def merge(self, request, **kwargs):
        group: ErrorTrackingGroup = self.get_object()
        merging_fingerprints: list[str] = request.data.get("merging_fingerprints", [])
        group.merge(merging_fingerprints)
        return Response({"success": True})
