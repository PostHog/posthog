from django.core.files.uploadedfile import UploadedFile
import structlog
import hashlib

from rest_framework import serializers, viewsets, status
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError

from django.conf import settings

from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action
from posthog.models.error_tracking import (
    ErrorTrackingIssue,
    ErrorTrackingSymbolSet,
    ErrorTrackingStackFrame,
    ErrorTrackingIssueAssignment,
)
from posthog.models.utils import uuid7
from posthog.storage import object_storage


ONE_GIGABYTE = 1024 * 1024 * 1024
JS_DATA_MAGIC = b"posthog_error_tracking"
JS_DATA_VERSION = 1
JS_DATA_TYPE_SOURCE_AND_MAP = 2

logger = structlog.get_logger(__name__)


class ObjectStorageUnavailable(Exception):
    pass


class ErrorTrackingIssueSerializer(serializers.ModelSerializer):
    class Meta:
        model = ErrorTrackingIssue
        fields = ["assignee", "status"]


class ErrorTrackingIssueViewSet(TeamAndOrgViewSetMixin, ForbidDestroyModel, viewsets.ModelViewSet):
    scope_object = "INTERNAL"
    queryset = ErrorTrackingIssue.objects.all()
    serializer_class = ErrorTrackingIssueSerializer

    def safely_get_queryset(self, queryset):
        return queryset.filter(team_id=self.team.id)

    @action(methods=["POST"], detail=True)
    def merge(self, request, **kwargs):
        issue: ErrorTrackingIssue = self.get_object()
        ids: list[str] = request.data.get("ids", [])
        issue.merge(issue_ids=ids)
        return Response({"success": True})

    @action(methods=["PATCH"], detail=True)
    def assign(self, request, **kwargs):
        assignee = request.data.get("assignee", None)

        if assignee:
            ErrorTrackingIssueAssignment.objects.update_or_create(
                issue_id=self.get_object().id,
                defaults={
                    "user_id": None if assignee["type"] == "user_group" else assignee["id"],
                    "user_group_id": None if assignee["type"] == "user" else assignee["id"],
                },
            )
        else:
            ErrorTrackingIssueAssignment.objects.filter(issue_id=self.get_object().id).delete()

        return Response({"success": True})


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


class ErrorTrackingSymbolSetViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
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
        # TODO: delete file from s3
        minified = request.FILES["minified"]
        source_map = request.FILES["source_map"]
        (storage_ptr, content_hash) = upload_symbol_set(minified, source_map, self.team_id)
        symbol_set.storage_ptr = storage_ptr
        symbol_set.content_hash = content_hash
        symbol_set.save()
        ErrorTrackingStackFrame.objects.filter(team=self.team, symbol_set=symbol_set).delete()
        return Response({"ok": True}, status=status.HTTP_204_NO_CONTENT)


def upload_symbol_set(minified: UploadedFile, source_map: UploadedFile, team_id) -> tuple[str, str]:
    js_data = construct_js_data_object(minified.read(), source_map.read())
    content_hash = hashlib.sha512(js_data).hexdigest()

    try:
        if settings.OBJECT_STORAGE_ENABLED:
            # TODO - maybe a gigabyte is too much?
            if len(js_data) > ONE_GIGABYTE:
                raise ValidationError(
                    code="file_too_large", detail="Combined source map and symbol set must be less than 1 gigabyte"
                )

            upload_path = f"{settings.OBJECT_STORAGE_ERROR_TRACKING_SOURCE_MAPS_FOLDER}/{str(uuid7())}"
            object_storage.write(upload_path, bytes(js_data))
            return (upload_path, content_hash)
        else:
            raise ObjectStorageUnavailable()
    except ObjectStorageUnavailable:
        raise ValidationError(
            code="object_storage_required",
            detail="Object storage must be available to allow source map uploads.",
        )


def construct_js_data_object(minified: bytes, source_map: bytes) -> bytearray:
    # See rust/cymbal/hacks/js_data.rs
    data = bytearray()
    data.extend(JS_DATA_MAGIC)
    data.extend(JS_DATA_VERSION.to_bytes(4, "little"))
    data.extend((JS_DATA_TYPE_SOURCE_AND_MAP).to_bytes(4, "little"))
    # TODO - this doesn't seem right?
    s_bytes = minified.decode("utf-8").encode("utf-8")
    data.extend(len(s_bytes).to_bytes(8, "little"))
    data.extend(s_bytes)
    sm_bytes = source_map.decode("utf-8").encode("utf-8")
    data.extend(len(sm_bytes).to_bytes(8, "little"))
    data.extend(sm_bytes)
    return data
