import structlog

from rest_framework import viewsets, request, response, serializers
from posthog.api.routing import TeamAndOrgViewSetMixin
from .forbid_destroy_model import ForbidDestroyModel

from posthog.models.error_tracking import ErrorTrackingStackFrame

FIFTY_MEGABYTES = 50 * 1024 * 1024

logger = structlog.get_logger(__name__)


class ObjectStorageUnavailable(Exception):
    pass


# class ErrorTrackingGroupSerializer(serializers.ModelSerializer):
#     class Meta:
#         model = ErrorTrackingGroup
#         fields = ["assignee", "status"]


# class ErrorTrackingGroupViewSet(TeamAndOrgViewSetMixin, ForbidDestroyModel, viewsets.ModelViewSet):
#     scope_object = "INTERNAL"
#     queryset = ErrorTrackingGroup.objects.all()
#     serializer_class = ErrorTrackingGroupSerializer

#     def safely_get_object(self, queryset) -> QuerySet:
#         stringified_fingerprint = self.kwargs["pk"]
#         fingerprint = json.loads(urlsafe_base64_decode(stringified_fingerprint))
#         group, _ = queryset.get_or_create(fingerprint=fingerprint, team=self.team)
#         return group

#     @action(methods=["POST"], detail=True)
#     def merge(self, request, **kwargs):
#         group: ErrorTrackingGroup = self.get_object()
#         merging_fingerprints: list[list[str]] = request.data.get("merging_fingerprints", [])
#         group.merge(merging_fingerprints)
#         return Response({"success": True})

#     @action(methods=["POST"], detail=False)
#     def upload_source_maps(self, request, **kwargs):
#         try:
#             if settings.OBJECT_STORAGE_ENABLED:
#                 file = request.FILES["source_map"]
#                 if file.size > FIFTY_MEGABYTES:
#                     raise ValidationError(code="file_too_large", detail="Source maps must be less than 50MB")

#                 upload_path = (
#                     f"{settings.OBJECT_STORAGE_ERROR_TRACKING_SOURCE_MAPS_FOLDER}/team-{self.team_id}/{file.name}"
#                 )

#                 object_storage.write(upload_path, file)
#                 return Response({"ok": True}, status=status.HTTP_201_CREATED)
#             else:
#                 raise ObjectStorageUnavailable()
#         except ObjectStorageUnavailable:
#             raise ValidationError(
#                 code="object_storage_required",
#                 detail="Object storage must be available to allow source map uploads.",
#             )


class ErrorTrackingStackFrameSerializer(serializers.ModelSerializer):
    class Meta:
        model = ErrorTrackingStackFrame
        fields = ["raw_id", "context"]


class ErrorTrackingStackFrameViewSet(TeamAndOrgViewSetMixin, ForbidDestroyModel, viewsets.ReadOnlyModelViewSet):
    scope_object = "INTERNAL"
    queryset = ErrorTrackingStackFrame.objects.all()
    serializer_class = ErrorTrackingStackFrameSerializer

    def list(self, request: request.Request, *args, **kwargs) -> response.Response:
        ids = request.GET.getlist("ids", [])
        queryset = self.filter_queryset(self.queryset.filter(team=self.team, raw_id__in=ids))
        serializer = self.get_serializer(queryset, many=True)
        return response.Response(serializer.data)
