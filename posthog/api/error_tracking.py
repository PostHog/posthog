from django.db.models import QuerySet
from rest_framework import serializers, viewsets

from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.error_tracking import ErrorTrackingGroup
from posthog.api.utils import action
from rest_framework.response import Response
from django.utils.http import urlsafe_base64_decode
import json


class ErrorTrackingGroupSerializer(serializers.ModelSerializer):
    class Meta:
        model = ErrorTrackingGroup
        fields = ["assignee", "status"]


class ErrorTrackingGroupViewSet(TeamAndOrgViewSetMixin, ForbidDestroyModel, viewsets.ModelViewSet):
    scope_object = "INTERNAL"
    queryset = ErrorTrackingGroup.objects.all()
    serializer_class = ErrorTrackingGroupSerializer

    def safely_get_object(self, queryset) -> QuerySet:
        stringified_fingerprint = self.kwargs["pk"]
        fingerprint = json.loads(urlsafe_base64_decode(stringified_fingerprint))
        group, _ = queryset.get_or_create(fingerprint=fingerprint, team=self.team)
        return group

    @action(methods=["POST"], detail=True)
    def merge(self, request, **kwargs):
        group: ErrorTrackingGroup = self.get_object()
        merging_fingerprints: list[list[str]] = request.data.get("merging_fingerprints", [])
        group.merge(merging_fingerprints)
        return Response({"success": True})
