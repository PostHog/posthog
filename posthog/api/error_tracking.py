import structlog

from rest_framework import serializers, viewsets, status
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError

from django.conf import settings

from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models import ErrorTrackingSymbolSet
from posthog.models.error_tracking import ErrorTrackingStackFrame
from posthog.models.utils import uuid7
from posthog.storage import object_storage


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


class ErrorTrackingStackFrameSerializer(serializers.ModelSerializer):
    symbol_set_ref = serializers.CharField(source="symbol_set.ref", default=None)

    class Meta:
        model = ErrorTrackingStackFrame
        fields = ["id", "raw_id", "created_at", "contents", "resolved", "context", "symbol_set_ref"]


class ErrorTrackingStackFrameViewSet(TeamAndOrgViewSetMixin, ForbidDestroyModel, viewsets.ReadOnlyModelViewSet):
    scope_object = "INTERNAL"
    queryset = ErrorTrackingStackFrame.objects.all()
    serializer_class = ErrorTrackingStackFrameSerializer

    def safely_get_queryset(self, queryset):
        if self.action == "list":
            raw_ids = self.request.GET.getlist("raw_ids", [])
            if raw_ids:
                queryset = self.queryset.filter(raw_id__in=raw_ids)

            symbol_set = self.request.GET.get("symbol_set", None)
            if symbol_set:
                queryset = self.queryset.filter(symbol_set=symbol_set)

        return queryset.select_related("symbol_set").filter(team_id=self.team.id)


class ErrorTrackingSymbolSetSerializer(serializers.ModelSerializer):
    class Meta:
        model = ErrorTrackingSymbolSet
        fields = ["id", "ref", "team_id", "created_at", "storage_ptr", "failure_reason"]
        read_only_fields = ["team_id"]


class ErrorTrackingSymbolSetViewSet(TeamAndOrgViewSetMixin, viewsets.ReadOnlyModelViewSet):
    scope_object = "INTERNAL"
    queryset = ErrorTrackingSymbolSet.objects.all()
    serializer_class = ErrorTrackingSymbolSetSerializer

    def safely_get_queryset(self, queryset):
        return queryset.filter(team_id=self.team.id)

    def destroy(self, request, *args, **kwargs):
        symbol_set = self.get_object()
        symbol_set.delete()
        # TODO: delete file from s3
        return Response(status=status.HTTP_204_NO_CONTENT)

    def update(self, request, *args, **kwargs) -> Response:
        symbol_set = self.get_object()
        symbol_set.delete()
        # TODO: delete file from s3
        storage_ptr = upload_symbol_set(request.FILES["source_map"], self.team_id)
        symbol_set.storage_ptr = storage_ptr
        symbol_set.save()
        return Response({"ok": True}, status=status.HTTP_204_NO_CONTENT)


def upload_symbol_set(file, team_id) -> str:
    try:
        if settings.OBJECT_STORAGE_ENABLED:
            if file.size > FIFTY_MEGABYTES:
                raise ValidationError(code="file_too_large", detail="Source maps must be less than 50MB")

            upload_path = f"{settings.OBJECT_STORAGE_ERROR_TRACKING_SOURCE_MAPS_FOLDER}/{str(uuid7())}"
            object_storage.write(upload_path, file)
            return upload_path
        else:
            raise ObjectStorageUnavailable()
    except ObjectStorageUnavailable:
        raise ValidationError(
            code="object_storage_required",
            detail="Object storage must be available to allow source map uploads.",
        )
