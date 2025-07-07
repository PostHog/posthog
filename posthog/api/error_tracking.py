from typing import Any, Optional

from django.core.files.uploadedfile import UploadedFile
from posthog.models.team.team import Team
import structlog
import hashlib

from rest_framework import serializers, viewsets, status, request
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import MultiPartParser, FileUploadParser, JSONParser

from django.http import JsonResponse
from django.conf import settings
from django.db import transaction

from common.hogvm.python.operation import Operation
from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.routing import TeamAndOrgViewSetMixin

from posthog.api.utils import action
from posthog.models.utils import UUIDT
from posthog.models.error_tracking import (
    ErrorTrackingIssue,
    ErrorTrackingRelease,
    ErrorTrackingSymbolSet,
    ErrorTrackingAssignmentRule,
    ErrorTrackingGroupingRule,
    ErrorTrackingSuppressionRule,
    ErrorTrackingStackFrame,
    ErrorTrackingIssueAssignment,
    ErrorTrackingIssueFingerprintV2,
)
from posthog.models.activity_logging.activity_log import log_activity, Detail, Change, load_activity
from posthog.models.activity_logging.activity_page import activity_page_response
from posthog.models.error_tracking.hogvm_stl import RUST_HOGVM_STL
from posthog.models.utils import uuid7
from posthog.storage import object_storage
from loginas.utils import is_impersonated_session
from posthog.hogql.property import property_to_expr
from posthog.hogql import ast

from posthog.tasks.email import send_error_tracking_issue_assigned
from posthog.hogql.compiler.bytecode import create_bytecode
from posthog.schema import PropertyGroupFilterValue

ONE_HUNDRED_MEGABYTES = 1024 * 1024 * 100
JS_DATA_MAGIC = b"posthog_error_tracking"
JS_DATA_VERSION = 1
JS_DATA_TYPE_SOURCE_AND_MAP = 2

logger = structlog.get_logger(__name__)


class ErrorTrackingIssueAssignmentSerializer(serializers.ModelSerializer):
    id = serializers.SerializerMethodField()
    type = serializers.SerializerMethodField()

    class Meta:
        model = ErrorTrackingIssueAssignment
        fields = ["id", "type"]

    def get_id(self, obj):
        return obj.user_id or obj.role_id

    def get_type(self, obj):
        return "role" if obj.role else "user"


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

        name_after = validated_data.get("name")
        name_before = instance.name
        name_updated = "name" in validated_data and name_after != name_before

        updated_instance = super().update(instance, validated_data)

        changes = []
        if status_updated:
            changes.append(
                Change(
                    type="ErrorTrackingIssue",
                    field="status",
                    before=status_before,
                    after=status_after,
                    action="changed",
                )
            )
        if name_updated:
            changes.append(
                Change(type="ErrorTrackingIssue", field="name", before=name_before, after=name_after, action="changed")
            )

        if changes:
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
                    changes=changes,
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
        # Make sure we don't delete the issue being merged into (defensive of frontend bugs)
        ids = [x for x in ids if x != str(issue.id)]
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

    @action(methods=["GET"], detail=False)
    def values(self, request: request.Request, **kwargs):
        queryset = self.get_queryset()
        value = request.GET.get("value", None)
        key = request.GET.get("key")

        issue_values = []
        if key and value:
            if key == "name":
                issue_values = queryset.filter(name__icontains=value).values_list("name", flat=True)
            elif key == "issue_description":
                issue_values = queryset.filter(description__icontains=value).values_list("description", flat=True)

        return Response([{"name": value} for value in issue_values])

    @action(methods=["POST"], detail=False)
    def bulk(self, request, **kwargs):
        action = request.data.get("action")
        status = request.data.get("status")
        issues = self.get_queryset().filter(id__in=request.data.get("ids", []))

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
            return Response(status=status.HTTP_404_NOT_FOUND)

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
                "user_id": None if assignee["type"] != "user" else assignee["id"],
                "role_id": None if assignee["type"] != "role" else assignee["id"],
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


class ErrorTrackingReleaseSerializer(serializers.ModelSerializer):
    class Meta:
        model = ErrorTrackingRelease
        fields = ["id", "hash_id", "team_id", "created_at", "metadata", "version", "project"]
        read_only_fields = ["team_id"]


class ErrorTrackingReleaseViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "error_tracking"
    queryset = ErrorTrackingRelease.objects.all()
    serializer_class = ErrorTrackingReleaseSerializer

    def safely_get_queryset(self, queryset):
        queryset = queryset.filter(team_id=self.team.id)

        return queryset

    def validate_hash_id(self, hash_id: str, assert_new: bool) -> str:
        if len(hash_id) > 128:
            raise ValueError("Hash id length cannot exceed 128 bytes")

        if assert_new and ErrorTrackingRelease.objects.filter(team=self.team, hash_id=hash_id).exists():
            raise ValueError(f"Hash id {hash_id} already in use")

        return hash_id

    def update(self, request, *args, **kwargs) -> Response:
        release = self.get_object()

        metadata = request.data.get("metadata")
        hash_id = request.data.get("hash_id")
        version = request.data.get("version")
        project = request.data.get("project")

        if metadata:
            release.metadata = metadata

        if version:
            version = str(version)
            release.version = version

        if project:
            project = str(project)
            release.project = project

        if hash_id and hash_id != release.hash_id:
            hash_id = str(hash_id)
            hash_id = self.validate_hash_id(hash_id, True)
            release.hash_id = hash_id

        release.save()
        return Response({"ok": True}, status=status.HTTP_204_NO_CONTENT)

    def create(self, request, *args, **kwargs) -> Response:
        id = UUIDT()  # We use this in the hash if one isn't set, and also as the id of the model
        metadata = request.data.get("metadata")
        hash_id = str(request.data.get("hash_id") or id)
        hash_id = self.validate_hash_id(hash_id, True)
        version = request.data.get("version")
        project = request.data.get("project")

        if not version:
            raise ValidationError("Version is required")

        if not project:
            raise ValidationError("Project is required")

        version = str(version)

        release = ErrorTrackingRelease.objects.create(
            id=id, team=self.team, hash_id=hash_id, metadata=metadata, project=project, version=version
        )

        serializer = ErrorTrackingReleaseSerializer(release)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


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
    scope_object_write_actions = [
        "bulk_start_upload",
        "bulk_finish_upload",
        "start_upload",
        "finish_upload",
        "destroy",
        "update",
        "create",
    ]

    def safely_get_queryset(self, queryset):
        queryset = queryset.filter(team_id=self.team.id)
        params = self.request.GET.dict()
        status = params.get("status")
        order_by = params.get("order_by")

        if status == "valid":
            queryset = queryset.filter(storage_ptr__isnull=False)
        elif status == "invalid":
            queryset = queryset.filter(storage_ptr__isnull=True)

        if order_by:
            allowed_fields = ["created_at", "-created_at", "ref", "-ref"]
            if order_by in allowed_fields:
                queryset = queryset.order_by(order_by)

        return queryset

    def destroy(self, request, *args, **kwargs):
        symbol_set = self.get_object()
        symbol_set.delete()
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
        multipart = request.query_params.get("multipart", False)
        release_id = request.query_params.get("release_id", None)

        if not chunk_id:
            return Response({"detail": "chunk_id query parameter is required"}, status=status.HTTP_400_BAD_REQUEST)

        if multipart:
            data = bytearray()
            for chunk in request.FILES["file"].chunks():
                data.extend(chunk)
        else:
            # legacy: older versions of the CLI did not use multipart uploads
            # file added to the request data by the FileUploadParser
            data = request.data["file"].read()

        (storage_ptr, content_hash) = upload_content(bytearray(data))
        create_symbol_set(chunk_id, self.team, release_id, storage_ptr, content_hash)

        return Response({"ok": True}, status=status.HTTP_201_CREATED)

    @action(methods=["POST"], detail=False)
    def start_upload(self, request, **kwargs):
        chunk_id = request.query_params.get("chunk_id", None)
        release_id = request.query_params.get("release_id", None)

        if not settings.OBJECT_STORAGE_ENABLED:
            raise ValidationError(
                code="object_storage_required",
                detail="Object storage must be available to allow source map uploads.",
            )

        if not chunk_id:
            return Response({"detail": "chunk_id query parameter is required"}, status=status.HTTP_400_BAD_REQUEST)

        file_key = generate_symbol_set_file_key()
        presigned_url = object_storage.get_presigned_post(
            file_key=file_key,
            conditions=[["content-length-range", 0, ONE_HUNDRED_MEGABYTES]],
            expiration=60,
        )

        symbol_set = create_symbol_set(chunk_id, self.team, release_id, file_key)

        return Response(
            {"presigned_url": presigned_url, "symbol_set_id": str(symbol_set.pk)}, status=status.HTTP_201_CREATED
        )

    @action(methods=["PUT"], detail=True, parser_classes=[JSONParser])
    def finish_upload(self, request, **kwargs):
        content_hash = request.data.get("content_hash")

        if not content_hash:
            raise ValidationError(
                code="content_hash_required",
                detail="A content hash must be provided to complete symbol set upload.",
            )

        if not settings.OBJECT_STORAGE_ENABLED:
            raise ValidationError(
                code="object_storage_required",
                detail="Object storage must be available to allow source map uploads.",
            )

        symbol_set = self.get_object()
        s3_upload = object_storage.head_object(file_key=symbol_set.storage_ptr)

        if s3_upload:
            content_length = s3_upload.get("ContentLength")

            if not content_length or content_length > ONE_HUNDRED_MEGABYTES:
                symbol_set.delete()

                raise ValidationError(
                    code="file_too_large",
                    detail="The uploaded symbol set file was too large.",
                )
        else:
            raise ValidationError(
                code="file_not_found",
                detail="No file has been uploaded for the symbol set.",
            )

        if not symbol_set.content_hash:
            symbol_set.content_hash = content_hash
            symbol_set.save()

        return Response({"success": True}, status=status.HTTP_200_OK)

    @action(methods=["POST"], detail=False, parser_classes=[JSONParser])
    def bulk_start_upload(self, request, **kwargs):
        # Extract a list of chunk IDs from the request json
        chunk_ids = request.data.get("chunk_ids")
        # Grab the release ID from the request json
        release_id = request.data.get("release_id", None)
        if not chunk_ids:
            return Response({"detail": "chunk_ids query parameter is required"}, status=status.HTTP_400_BAD_REQUEST)

        if not settings.OBJECT_STORAGE_ENABLED:
            raise ValidationError(
                code="object_storage_required",
                detail="Object storage must be available to allow source map uploads.",
            )

        # For each of the chunk IDs, make a new symbol set and presigned URL
        id_url_map = {}
        for chunk_id in chunk_ids:
            file_key = generate_symbol_set_file_key()
            presigned_url = object_storage.get_presigned_post(
                file_key=file_key,
                conditions=[["content-length-range", 0, ONE_HUNDRED_MEGABYTES]],
                expiration=60,
            )
            symbol_set = create_symbol_set(chunk_id, self.team, release_id, file_key)
            id_url_map[chunk_id] = {"presigned_url": presigned_url, "symbol_set_id": str(symbol_set.pk)}

        return Response({"id_map": id_url_map}, status=status.HTTP_201_CREATED)

    @action(methods=["POST"], detail=False, parser_classes=[JSONParser])
    def bulk_finish_upload(self, request, **kwargs):
        # Get the map of symbol_set_id:content_hashes
        content_hashes = request.data.get("content_hashes", {})
        if not content_hashes:
            return Response(
                {"detail": "content_hashes query parameter is required"}, status=status.HTTP_400_BAD_REQUEST
            )

        if not settings.OBJECT_STORAGE_ENABLED:
            raise ValidationError(
                code="object_storage_required",
                detail="Object storage must be available to allow source map uploads.",
            )

        try:
            for symbol_set_id, content_hash in content_hashes.items():
                symbol_set = ErrorTrackingSymbolSet.objects.get(id=symbol_set_id, team=self.team)
                s3_upload = None
                if symbol_set.storage_ptr:
                    s3_upload = object_storage.head_object(file_key=symbol_set.storage_ptr)

                if s3_upload:
                    content_length = s3_upload.get("ContentLength")

                    if not content_length or content_length > ONE_HUNDRED_MEGABYTES:
                        symbol_set.delete()

                        raise ValidationError(
                            code="file_too_large",
                            detail="The uploaded symbol set file was too large.",
                        )
                else:
                    raise ValidationError(
                        code="file_not_found",
                        detail="No file has been uploaded for the symbol set.",
                    )

                if not symbol_set.content_hash:
                    symbol_set.content_hash = content_hash
                    symbol_set.save()
        except Exception:
            for id in content_hashes.keys():
                # Try to clean up the symbol sets preemptively if the upload fails
                try:
                    symbol_set = ErrorTrackingSymbolSet.objects.all().filter(id=id, team=self.team).get()
                    symbol_set.delete()
                except Exception:
                    pass

            raise

        return Response({"success": True}, status=status.HTTP_201_CREATED)


class ErrorTrackingAssignmentRuleSerializer(serializers.ModelSerializer):
    assignee = serializers.SerializerMethodField()

    class Meta:
        model = ErrorTrackingAssignmentRule
        fields = ["id", "filters", "assignee"]
        read_only_fields = ["team_id"]

    def get_assignee(self, obj):
        if obj.user_id:
            return {"type": "user", "id": obj.user_id}
        elif obj.role_id:
            return {"type": "role", "id": obj.role_id}
        return None


class ErrorTrackingAssignmentRuleViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "error_tracking"
    queryset = ErrorTrackingAssignmentRule.objects.all()
    serializer_class = ErrorTrackingAssignmentRuleSerializer

    def safely_get_queryset(self, queryset):
        return queryset.filter(team_id=self.team.id)

    def update(self, request, *args, **kwargs) -> Response:
        assignment_rule = self.get_object()
        assignee = request.data.get("assignee")
        json_filters = request.data.get("filters")

        if json_filters:
            parsed_filters = PropertyGroupFilterValue(**json_filters)
            assignment_rule.filters = json_filters
            assignment_rule.bytecode = generate_byte_code(self.team, parsed_filters)

        if assignee:
            assignment_rule.user_id = None if assignee["type"] != "user" else assignee["id"]
            assignment_rule.role_id = None if assignee["type"] != "role" else assignee["id"]

        assignment_rule.save()

        return Response({"ok": True}, status=status.HTTP_204_NO_CONTENT)

    def create(self, request, *args, **kwargs) -> Response:
        json_filters = request.data.get("filters")
        assignee = request.data.get("assignee", None)

        if not json_filters:
            return Response({"error": "Filters are required"}, status=status.HTTP_400_BAD_REQUEST)
        if not assignee:
            return Response({"error": "Assignee is required"}, status=status.HTTP_400_BAD_REQUEST)

        parsed_filters = PropertyGroupFilterValue(**json_filters)

        bytecode = generate_byte_code(self.team, parsed_filters)

        assignment_rule = ErrorTrackingAssignmentRule.objects.create(
            team=self.team,
            filters=json_filters,
            bytecode=bytecode,
            order_key=0,
            user_id=None if assignee["type"] != "user" else assignee["id"],
            role_id=None if assignee["type"] != "role" else assignee["id"],
        )

        serializer = ErrorTrackingAssignmentRuleSerializer(assignment_rule)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class ErrorTrackingGroupingRuleSerializer(serializers.ModelSerializer):
    assignee = serializers.SerializerMethodField()

    class Meta:
        model = ErrorTrackingGroupingRule
        fields = ["id", "filters", "assignee"]
        read_only_fields = ["team_id"]

    def get_assignee(self, obj):
        if obj.user_id:
            return {"type": "user", "id": obj.user_id}
        elif obj.role_id:
            return {"type": "role", "id": obj.role_id}
        return None


class ErrorTrackingGroupingRuleViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "error_tracking"
    queryset = ErrorTrackingGroupingRule.objects.all()
    serializer_class = ErrorTrackingGroupingRuleSerializer

    def safely_get_queryset(self, queryset):
        return queryset.filter(team_id=self.team.id)

    def update(self, request, *args, **kwargs) -> Response:
        grouping_rule = self.get_object()
        assignee = request.data.get("assignee")
        json_filters = request.data.get("filters")
        description = request.data.get("description")

        if json_filters:
            parsed_filters = PropertyGroupFilterValue(**json_filters)
            grouping_rule.filters = json_filters
            grouping_rule.bytecode = generate_byte_code(self.team, parsed_filters)

        if assignee:
            grouping_rule.user_id = None if assignee["type"] != "user" else assignee["id"]
            grouping_rule.role_id = None if assignee["type"] != "role" else assignee["id"]

        if description:
            grouping_rule.description = description

        grouping_rule.save()

        return Response({"ok": True}, status=status.HTTP_204_NO_CONTENT)

    def create(self, request, *args, **kwargs) -> Response:
        json_filters = request.data.get("filters")
        assignee = request.data.get("assignee", None)
        description = request.data.get("description", None)

        if not json_filters:
            return Response({"error": "Filters are required"}, status=status.HTTP_400_BAD_REQUEST)

        parsed_filters = PropertyGroupFilterValue(**json_filters)
        bytecode = generate_byte_code(self.team, parsed_filters)

        grouping_rule = ErrorTrackingGroupingRule.objects.create(
            team=self.team,
            filters=json_filters,
            bytecode=bytecode,
            order_key=0,
            user_id=None if (not assignee or assignee["type"] != "user") else assignee["id"],
            role_id=None if (not assignee or assignee["type"] != "role") else assignee["id"],
            description=description,
        )

        serializer = ErrorTrackingGroupingRuleSerializer(grouping_rule)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class ErrorTrackingSuppressionRuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = ErrorTrackingSuppressionRule
        fields = ["id", "filters", "order_key"]
        read_only_fields = ["team_id"]


class ErrorTrackingSuppressionRuleViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "error_tracking"
    queryset = ErrorTrackingSuppressionRule.objects.all()
    serializer_class = ErrorTrackingSuppressionRuleSerializer

    def safely_get_queryset(self, queryset):
        return queryset.filter(team_id=self.team.id)

    def update(self, request, *args, **kwargs) -> Response:
        suppression_rule = self.get_object()
        filters = request.data.get("filters")

        if filters:
            suppression_rule.filters = filters

        suppression_rule.save()

        return Response({"ok": True}, status=status.HTTP_204_NO_CONTENT)

    def create(self, request, *args, **kwargs) -> Response:
        filters = request.data.get("filters")

        if not filters:
            return Response({"error": "Filters are required"}, status=status.HTTP_400_BAD_REQUEST)

        suppression_rule = ErrorTrackingSuppressionRule.objects.create(
            team=self.team,
            filters=filters,
            order_key=0,
        )

        serializer = ErrorTrackingSuppressionRuleSerializer(suppression_rule)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


def create_symbol_set(
    chunk_id: str, team: Team, release_id: str | None, storage_ptr: str, content_hash: Optional[str] = None
):
    if release_id:
        objects = ErrorTrackingRelease.objects.all().filter(team=team, id=release_id)
        if len(objects) < 1:
            raise ValueError(f"Unknown release: {release_id}")
        release = objects[0]
    else:
        release = None

    with transaction.atomic():
        # Use update_or_create for proper upsert behavior
        symbol_set, created = ErrorTrackingSymbolSet.objects.update_or_create(
            team=team,
            ref=chunk_id,
            release=release,
            defaults={
                "storage_ptr": storage_ptr,
                "content_hash": content_hash,
                "failure_reason": None,
            },
        )

        # Delete any existing frames associated with this symbol set
        ErrorTrackingStackFrame.objects.filter(team=team, symbol_set=symbol_set).delete()

        return symbol_set


def upload_symbol_set(minified: UploadedFile, source_map: UploadedFile) -> tuple[str, str]:
    js_data = construct_js_data_object(minified.read(), source_map.read())
    return upload_content(js_data)


def upload_content(content: bytearray) -> tuple[str, str]:
    content_hash = hashlib.sha512(content).hexdigest()

    if not settings.OBJECT_STORAGE_ENABLED:
        raise ValidationError(
            code="object_storage_required",
            detail="Object storage must be available to allow source map uploads.",
        )

    if len(content) > ONE_HUNDRED_MEGABYTES:
        raise ValidationError(
            code="file_too_large", detail="Combined source map and symbol set must be less than 100MB"
        )

    upload_path = generate_symbol_set_file_key()
    object_storage.write(upload_path, bytes(content))
    return (upload_path, content_hash)


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


def generate_byte_code(team: Team, props: PropertyGroupFilterValue):
    expr = property_to_expr(props, team, strict=True)
    # The rust HogVM expects a return statement, so we wrap the compiled filter expression in one
    with_return = ast.ReturnStatement(expr=expr)
    bytecode = create_bytecode(with_return).bytecode
    validate_bytecode(bytecode)
    return bytecode


def validate_bytecode(bytecode: list[Any]) -> None:
    for i, op in enumerate(bytecode):
        if not isinstance(op, Operation):
            continue
        if op == Operation.CALL_GLOBAL:
            name = bytecode[i + 1]
            if not isinstance(name, str):
                raise ValidationError(f"Expected string for global function name, got {type(name)}")
            if name not in RUST_HOGVM_STL:
                raise ValidationError(f"Unknown global function: {name}")


def get_suppression_rules(team: Team):
    return list(ErrorTrackingSuppressionRule.objects.filter(team=team).values_list("filters", flat=True))


def generate_symbol_set_file_key():
    return f"{settings.OBJECT_STORAGE_ERROR_TRACKING_SOURCE_MAPS_FOLDER}/{str(uuid7())}"
