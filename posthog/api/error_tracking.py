from django.core.files.uploadedfile import UploadedFile
import structlog
import hashlib

from rest_framework import serializers, viewsets, status, request
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import MultiPartParser, FileUploadParser

from django.http import JsonResponse
from django.conf import settings
from django.db import transaction

from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action
from posthog.models.error_tracking import (
    ErrorTrackingIssue,
    ErrorTrackingSymbolSet,
    ErrorTrackingStackFrame,
    ErrorTrackingIssueAssignment,
    ErrorTrackingIssueFingerprintV2,
)
from posthog.models.activity_logging.activity_log import log_activity, Detail, Change, load_activity
from posthog.models.activity_logging.activity_page import activity_page_response
from posthog.models.utils import uuid7
from posthog.storage import object_storage
from loginas.utils import is_impersonated_session

from posthog.tasks.email import send_error_tracking_issue_assigned

ONE_GIGABYTE = 1024 * 1024 * 1024
JS_DATA_MAGIC = b"posthog_error_tracking"
JS_DATA_VERSION = 1
JS_DATA_TYPE_SOURCE_AND_MAP = 2

logger = structlog.get_logger(__name__)


class ObjectStorageUnavailable(Exception):
    pass


class ErrorTrackingIssueAssignmentSerializer(serializers.ModelSerializer):
    id = serializers.SerializerMethodField()
    type = serializers.SerializerMethodField()

    class Meta:
        model = ErrorTrackingIssueAssignment
        fields = ["id", "type"]

    def get_id(self, obj):
        return obj.user_id or obj.user_group_id

    def get_type(self, obj):
        return "user_group" if obj.user_group else "user"


class ErrorTrackingIssueSerializer(serializers.ModelSerializer):
    first_seen = serializers.DateTimeField()
    assignee = ErrorTrackingIssueAssignmentSerializer(source="assignment")

    class Meta:
        model = ErrorTrackingIssue
        fields = ["id", "status", "name", "description", "first_seen", "assignee"]

    def update(self, instance, validated_data):
        team = instance.team
        status_after = validated_data.get("status")
        status_before = instance.status
        status_updated = "status" in validated_data and status_after != status_before

        updated_instance = super().update(instance, validated_data)

        if status_updated:
            log_activity(
                organization_id=team.organization.id,
                team_id=team.id,
                user=self.context["request"].user,
                was_impersonated=is_impersonated_session(self.context["request"]),
                item_id=str(updated_instance.id),
                scope="ErrorTrackingIssue",
                activity="updated",
                detail=Detail(
                    name=instance.name,
                    changes=[
                        Change(
                            type="ErrorTrackingIssue",
                            field="status",
                            before=status_before,
                            after=status_after,
                            action="changed",
                        )
                    ],
                ),
            )

        return updated_instance


class ErrorTrackingIssueViewSet(TeamAndOrgViewSetMixin, ForbidDestroyModel, viewsets.ModelViewSet):
    scope_object = "INTERNAL"
    queryset = ErrorTrackingIssue.objects.with_first_seen().all()
    serializer_class = ErrorTrackingIssueSerializer

    def safely_get_queryset(self, queryset):
        return queryset.filter(team_id=self.team.id)

    def retrieve(self, request, *args, **kwargs):
        fingerprint = self.request.GET.get("fingerprint")
        if fingerprint:
            fingerprint_queryset = ErrorTrackingIssueFingerprintV2.objects.select_related("issue").filter(
                team=self.team
            )
            record = fingerprint_queryset.filter(fingerprint=fingerprint).first()

            if record:
                if not str(record.issue_id) == self.kwargs.get("pk"):
                    return JsonResponse({"issue_id": record.issue_id}, status=status.HTTP_308_PERMANENT_REDIRECT)

                issue_with_first_seen = ErrorTrackingIssue.objects.with_first_seen().get(id=record.issue_id)
                serializer = self.get_serializer(issue_with_first_seen)
                return Response(serializer.data)

        return super().retrieve(request, *args, **kwargs)

    @action(methods=["POST"], detail=True)
    def merge(self, request, **kwargs):
        issue: ErrorTrackingIssue = self.get_object()
        ids: list[str] = request.data.get("ids", [])
        issue.merge(issue_ids=ids)
        return Response({"success": True})

    @action(methods=["PATCH"], detail=True)
    def assign(self, request, **kwargs):
        assignee = request.data.get("assignee", None)
        instance = self.get_object()

        assign_issue(
            instance, assignee, self.organization, request.user, self.team_id, is_impersonated_session(request)
        )

        return Response({"success": True})

    @action(methods=["POST"], detail=False)
    def bulk(self, request, **kwargs):
        action = request.data.get("action")
        status = request.data.get("status")
        issues = self.queryset.filter(id__in=request.data.get("ids", []))

        with transaction.atomic():
            if action == "set_status":
                new_status = get_status_from_string(status)
                if new_status is None:
                    raise ValidationError("Invalid status")
                for issue in issues:
                    log_activity(
                        organization_id=self.organization.id,
                        team_id=self.team_id,
                        user=request.user,
                        was_impersonated=is_impersonated_session(request),
                        item_id=issue.id,
                        scope="ErrorTrackingIssue",
                        activity="updated",
                        detail=Detail(
                            name=issue.name,
                            changes=[
                                Change(
                                    type="ErrorTrackingIssue",
                                    action="changed",
                                    field="status",
                                    before=issue.status,
                                    after=new_status,
                                )
                            ],
                        ),
                    )

                issues.update(status=new_status)
            elif action == "assign":
                assignee = request.data.get("assignee", None)

                for issue in issues:
                    assign_issue(
                        issue, assignee, self.organization, request.user, self.team_id, is_impersonated_session(request)
                    )

        return Response({"success": True})

    @action(methods=["GET"], url_path="activity", detail=False, required_scopes=["activity_log:read"])
    def all_activity(self, request: request.Request, **kwargs):
        limit = int(request.query_params.get("limit", "10"))
        page = int(request.query_params.get("page", "1"))

        activity_page = load_activity(scope="ErrorTrackingIssue", team_id=self.team_id, limit=limit, page=page)
        return activity_page_response(activity_page, limit, page, request)

    @action(methods=["GET"], detail=True, required_scopes=["activity_log:read"])
    def activity(self, request: request.Request, **kwargs):
        limit = int(request.query_params.get("limit", "10"))
        page = int(request.query_params.get("page", "1"))

        item_id = kwargs["pk"]
        if not ErrorTrackingIssue.objects.filter(id=item_id, team_id=self.team_id).exists():
            return Response("", status=status.HTTP_404_NOT_FOUND)

        activity_page = load_activity(
            scope="ErrorTrackingIssue",
            team_id=self.team_id,
            item_ids=[str(item_id)],
            limit=limit,
            page=page,
        )
        return activity_page_response(activity_page, limit, page, request)


def get_status_from_string(status: str) -> ErrorTrackingIssue.Status | None:
    match status:
        case "active":
            return ErrorTrackingIssue.Status.ACTIVE
        case "resolved":
            return ErrorTrackingIssue.Status.RESOLVED
        case "suppressed":
            return ErrorTrackingIssue.Status.SUPPRESSED
    return None


def assign_issue(issue: ErrorTrackingIssue, assignee, organization, user, team_id, was_impersonated):
    assignment_before = ErrorTrackingIssueAssignment.objects.filter(issue_id=issue.id).first()
    serialized_assignment_before = (
        ErrorTrackingIssueAssignmentSerializer(assignment_before).data if assignment_before else None
    )

    if assignee:
        assignment_after, _ = ErrorTrackingIssueAssignment.objects.update_or_create(
            issue_id=issue.id,
            defaults={
                "user_id": None if assignee["type"] == "user_group" else assignee["id"],
                "user_group_id": None if assignee["type"] == "user" else assignee["id"],
            },
        )

        send_error_tracking_issue_assigned(assignment_after, user)

        serialized_assignment_after = (
            ErrorTrackingIssueAssignmentSerializer(assignment_after).data if assignment_after else None
        )
    else:
        if assignment_before:
            assignment_before.delete()
        serialized_assignment_after = None

    log_activity(
        organization_id=organization.id,
        team_id=team_id,
        user=user,
        was_impersonated=was_impersonated,
        item_id=str(issue.id),
        scope="ErrorTrackingIssue",
        activity="assigned",
        detail=Detail(
            name=issue.name,
            changes=[
                Change(
                    type="ErrorTrackingIssue",
                    field="assignee",
                    before=serialized_assignment_before,
                    after=serialized_assignment_after,
                    action="changed",
                )
            ],
        ),
    )


class ErrorTrackingStackFrameSerializer(serializers.ModelSerializer):
    symbol_set_ref = serializers.CharField(source="symbol_set.ref", default=None)

    class Meta:
        model = ErrorTrackingStackFrame
        fields = ["id", "raw_id", "created_at", "contents", "resolved", "context", "symbol_set_ref"]


class ErrorTrackingStackFrameViewSet(TeamAndOrgViewSetMixin, ForbidDestroyModel, viewsets.ReadOnlyModelViewSet):
    scope_object = "INTERNAL"
    queryset = ErrorTrackingStackFrame.objects.all()
    serializer_class = ErrorTrackingStackFrameSerializer

    @action(methods=["POST"], detail=False)
    def batch_get(self, request, **kwargs):
        raw_ids = request.data.get("raw_ids", [])
        symbol_set = request.data.get("symbol_set", None)

        queryset = self.queryset.filter(team_id=self.team.id)

        if raw_ids:
            queryset = queryset.filter(raw_id__in=raw_ids)

        if symbol_set:
            queryset = queryset.filter(symbol_set=symbol_set)

        serializer = self.get_serializer(queryset, many=True)
        return Response({"results": serializer.data})


class ErrorTrackingSymbolSetSerializer(serializers.ModelSerializer):
    class Meta:
        model = ErrorTrackingSymbolSet
        fields = ["id", "ref", "team_id", "created_at", "storage_ptr", "failure_reason"]
        read_only_fields = ["team_id"]


class ErrorTrackingSymbolSetViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "error_tracking"
    queryset = ErrorTrackingSymbolSet.objects.all()
    serializer_class = ErrorTrackingSymbolSetSerializer
    parser_classes = [MultiPartParser, FileUploadParser]

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
        (storage_ptr, content_hash) = upload_symbol_set(minified, source_map)
        symbol_set.storage_ptr = storage_ptr
        symbol_set.content_hash = content_hash
        symbol_set.failure_reason = None
        symbol_set.save()
        ErrorTrackingStackFrame.objects.filter(team=self.team, symbol_set=symbol_set).delete()
        return Response({"ok": True}, status=status.HTTP_204_NO_CONTENT)

    def create(self, request, *args, **kwargs) -> Response:
        # pull the symbol set reference from the query params
        chunk_id = request.query_params.get("chunk_id", None)
        if not chunk_id:
            return Response({"detail": "chunk_id query parameter is required"}, status=status.HTTP_400_BAD_REQUEST)

        # file added to the request data by the FileUploadParser
        data = request.data["file"].read()
        (storage_ptr, content_hash) = upload_content(bytearray(data))

        with transaction.atomic():
            # Use update_or_create for proper upsert behavior
            symbol_set, created = ErrorTrackingSymbolSet.objects.update_or_create(
                team=self.team,
                ref=chunk_id,
                defaults={
                    "storage_ptr": storage_ptr,
                    "content_hash": content_hash,
                    "failure_reason": None,
                },
            )

            # Delete any existing frames associated with this symbol set
            ErrorTrackingStackFrame.objects.filter(team=self.team, symbol_set=symbol_set).delete()

        return Response({"ok": True}, status=status.HTTP_201_CREATED)


def upload_symbol_set(minified: UploadedFile, source_map: UploadedFile) -> tuple[str, str]:
    js_data = construct_js_data_object(minified.read(), source_map.read())
    return upload_content(js_data)


def upload_content(content: bytearray) -> tuple[str, str]:
    content_hash = hashlib.sha512(content).hexdigest()

    try:
        if settings.OBJECT_STORAGE_ENABLED:
            # TODO - maybe a gigabyte is too much?
            if len(content) > ONE_GIGABYTE:
                raise ValidationError(
                    code="file_too_large", detail="Combined source map and symbol set must be less than 1 gigabyte"
                )

            upload_path = f"{settings.OBJECT_STORAGE_ERROR_TRACKING_SOURCE_MAPS_FOLDER}/{str(uuid7())}"
            object_storage.write(upload_path, bytes(content))
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
