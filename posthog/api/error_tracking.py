import hashlib
import requests
import json

from rest_framework import serializers, viewsets
from rest_framework.response import Response

from django.db.models import QuerySet
from django.conf import settings
from django.utils.http import urlsafe_base64_decode

from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.models.error_tracking import ErrorTrackingGroup
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action


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

    @action(methods=["POST"], detail=False)
    def upload_sourcemap(self, request, **kwargs):
        sourcemap_url = request.GET.get("url", "")

        url_hash = hashlib.md5(sourcemap_url.encode()).hexdigest()
        upload_path = f"{settings.OBJECT_STORAGE_ERROR_TRACKING_SOURCEMAPS_FOLDER}/team-{self.team_id}/{url_hash}"

        content = "This is the content I want to upload"

        res = requests.get(sourcemap_url)

        return Response({"contents": res.json()})

        data = res.json()

        print(data)

        # object_storage.write(
        #     upload_path,
        #     content,
        #     # extras={"ContentType": "application/json", "ContentEncoding": "gzip"},
        # )

        return Response({"ok": True})
