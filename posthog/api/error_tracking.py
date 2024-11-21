import structlog

from rest_framework import mixins, serializers, viewsets, status, response
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError

from django.conf import settings

from drf_spectacular.utils import extend_schema

from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action
from posthog.models import ErrorTrackingSymbolSet
from posthog.models.error_tracking import ErrorTrackingStackFrame
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
    class Meta:
        model = ErrorTrackingStackFrame
        fields = ["raw_id", "context"]


class ErrorTrackingStackFrameViewSet(TeamAndOrgViewSetMixin, ForbidDestroyModel, viewsets.ReadOnlyModelViewSet):
    scope_object = "INTERNAL"
    queryset = ErrorTrackingStackFrame.objects.all()
    serializer_class = ErrorTrackingStackFrameSerializer

    @action(methods=["GET"], detail=False)
    def contexts(self, request, **kwargs) -> response.Response:
        ids = request.GET.getlist("ids", [])
        queryset = self.filter_queryset(self.queryset.filter(team=self.team, raw_id__in=ids))
        serializer = self.get_serializer(queryset, many=True)
        keyed_data = {frame["raw_id"]: frame["context"] for frame in serializer.data}
        return response.Response(keyed_data)


class ErrorTrackingSymbolSetSerializer(serializers.ModelSerializer):
    class Meta:
        model = ErrorTrackingSymbolSet
        fields = ["ref"]


class ErrorTrackingSymbolSetViewSet(TeamAndOrgViewSetMixin, mixins.UpdateModelMixin, viewsets.GenericViewSet):
    scope_object = "INTERNAL"
    queryset = ErrorTrackingSymbolSet.objects.all()
    serializer_class = ErrorTrackingSymbolSetSerializer

    def update(self, request, *args, **kwargs) -> Response:
        symbol_set = self.get_object()
        storage_ptr = upload_symbol_set(request.FILES["source_map"], self.team_id)
        symbol_set.storage_ptr = storage_ptr
        symbol_set.save()
        # TODO: cascade delete the associated frame resolutions
        return Response({"ok": True}, status=status.HTTP_204_NO_CONTENT)

    @extend_schema(exclude=True)
    @action(methods=["GET"], detail=False)
    def missing(self, request, **kwargs):
        missing_symbol_sets = self.queryset.filter(team=self.team, storage_ptr=None)
        serializer = self.get_serializer(missing_symbol_sets, many=True)
        return Response(serializer.data)


def upload_symbol_set(file, team_id) -> str:
    try:
        if settings.OBJECT_STORAGE_ENABLED:
            if file.size > FIFTY_MEGABYTES:
                raise ValidationError(code="file_too_large", detail="Source maps must be less than 50MB")

            upload_path = f"{settings.OBJECT_STORAGE_ERROR_TRACKING_SOURCE_MAPS_FOLDER}/team-{team_id}/{file.name}"
            object_storage.write(upload_path, file)
            return upload_path
        else:
            raise ObjectStorageUnavailable()
    except ObjectStorageUnavailable:
        raise ValidationError(
            code="object_storage_required",
            detail="Object storage must be available to allow source map uploads.",
        )
