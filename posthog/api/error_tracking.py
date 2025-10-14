import json
import hashlib
from datetime import datetime
from typing import Any, Optional, Protocol, TypeVar

from django.conf import settings
from django.core.files.uploadedfile import UploadedFile
from django.db import transaction
from django.http import JsonResponse

import structlog
import posthoganalytics
from loginas.utils import is_impersonated_session
from rest_framework import request, serializers, status, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import FileUploadParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from posthog.schema import PropertyGroupFilterValue

from posthog.hogql import ast
from posthog.hogql.compiler.bytecode import create_bytecode
from posthog.hogql.property import property_to_expr

from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action
from posthog.event_usage import groups
from posthog.models.activity_logging.activity_log import Change, Detail, load_activity, log_activity
from posthog.models.activity_logging.activity_page import activity_page_response
from posthog.models.error_tracking import (
    ErrorTrackingAssignmentRule,
    ErrorTrackingExternalReference,
    ErrorTrackingGroupingRule,
    ErrorTrackingIssue,
    ErrorTrackingIssueAssignment,
    ErrorTrackingIssueFingerprintV2,
    ErrorTrackingRelease,
    ErrorTrackingStackFrame,
    ErrorTrackingSuppressionRule,
    ErrorTrackingSymbolSet,
    resolve_fingerprints_for_issues,
)
from posthog.models.error_tracking.hogvm_stl import RUST_HOGVM_STL
from posthog.models.integration import GitHubIntegration, Integration, LinearIntegration
from posthog.models.plugin import sync_execute
from posthog.models.team.team import Team
from posthog.models.utils import UUIDT, uuid7
from posthog.storage import object_storage
from posthog.tasks.email import send_error_tracking_issue_assigned

from common.hogvm.python.operation import Operation

ONE_HUNDRED_MEGABYTES = 1024 * 1024 * 100
JS_DATA_MAGIC = b"posthog_error_tracking"
JS_DATA_VERSION = 1
JS_DATA_TYPE_SOURCE_AND_MAP = 2
PRESIGNED_MULTIPLE_UPLOAD_TIMEOUT = 60 * 5

# Error tracking embedding configuration defaults
DEFAULT_EMBEDDING_MODEL_NAME = "text-embedding-3-large"
DEFAULT_EMBEDDING_VERSION = 1
DEFAULT_MIN_DISTANCE_THRESHOLD = 0.10

logger = structlog.get_logger(__name__)


class ErrorTrackingExternalReferenceIntegrationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Integration
        fields = ["id", "kind", "display_name"]
        read_only_fields = ["id", "kind", "display_name"]


class ErrorTrackingExternalReferenceSerializer(serializers.ModelSerializer):
    config = serializers.JSONField(write_only=True)
    issue = serializers.PrimaryKeyRelatedField(write_only=True, queryset=ErrorTrackingIssue.objects.all())
    integration = ErrorTrackingExternalReferenceIntegrationSerializer(read_only=True)
    integration_id = serializers.PrimaryKeyRelatedField(
        write_only=True, queryset=Integration.objects.all(), source="integration"
    )
    external_url = serializers.SerializerMethodField()

    class Meta:
        model = ErrorTrackingExternalReference
        fields = ["id", "integration", "integration_id", "config", "issue", "external_url"]
        read_only_fields = ["external_url"]

    def get_external_url(self, reference: ErrorTrackingExternalReference) -> str:
        external_context: dict[str, str] = reference.external_context or {}
        if reference.integration.kind == Integration.IntegrationKind.LINEAR:
            url_key = LinearIntegration(reference.integration).url_key()
            return f"https://linear.app/{url_key}/issue/{external_context['id']}"
        elif reference.integration.kind == Integration.IntegrationKind.GITHUB:
            org = GitHubIntegration(reference.integration).organization()
            return f"https://github.com/{org}/{external_context['repository']}/issues/{external_context['number']}"
        raise ValidationError("Provider not supported")

    def validate(self, data):
        issue = data["issue"]
        integration = data["integration"]
        team = self.context["get_team"]()

        if issue.team_id != team.id:
            raise serializers.ValidationError("Issue does not belong to this team.")

        if integration.team_id != team.id:
            raise serializers.ValidationError("Integration does not belong to this team.")

        return data

    def create(self, validated_data) -> ErrorTrackingExternalReference:
        team = self.context["get_team"]()
        issue: ErrorTrackingIssue = validated_data.get("issue")
        integration: Integration = validated_data.get("integration")

        config: dict[str, Any] = validated_data.pop("config")

        if integration.kind == "github":
            external_context = GitHubIntegration(integration).create_issue(config)
        elif integration.kind == "linear":
            external_context = LinearIntegration(integration).create_issue(team.pk, issue.id, config)
        else:
            raise ValidationError("Provider not supported")

        instance = ErrorTrackingExternalReference.objects.create(
            issue=issue,
            integration=integration,
            external_context=external_context,
        )
        return instance


class ErrorTrackingExternalReferenceViewSet(TeamAndOrgViewSetMixin, ForbidDestroyModel, viewsets.ModelViewSet):
    scope_object = "INTERNAL"
    queryset = ErrorTrackingExternalReference.objects.all()
    serializer_class = ErrorTrackingExternalReferenceSerializer


class ErrorTrackingIssueAssignmentSerializer(serializers.ModelSerializer):
    id = serializers.SerializerMethodField()
    type = serializers.SerializerMethodField()

    class Meta:
        model = ErrorTrackingIssueAssignment
        fields = ["id", "type"]

    def get_id(self, obj):
        return obj.user_id if obj.user_id else str(obj.role_id) if obj.role_id else None

    def get_type(self, obj):
        return "role" if obj.role else "user"


class ErrorTrackingIssueSerializer(serializers.ModelSerializer):
    first_seen = serializers.DateTimeField()
    assignee = ErrorTrackingIssueAssignmentSerializer(source="assignment")
    external_issues = ErrorTrackingExternalReferenceSerializer(many=True)

    class Meta:
        model = ErrorTrackingIssue
        fields = ["id", "status", "name", "description", "first_seen", "assignee", "external_issues"]

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


class ErrorTrackingFingerprintSerializer(serializers.ModelSerializer):
    class Meta:
        model = ErrorTrackingIssueFingerprintV2
        fields = ["fingerprint", "issue_id"]


class ErrorTrackingFingerprintViewSet(TeamAndOrgViewSetMixin, ForbidDestroyModel, viewsets.ReadOnlyModelViewSet):
    scope_object = "error_tracking"
    queryset = ErrorTrackingIssueFingerprintV2.objects.all()
    serializer_class = ErrorTrackingFingerprintSerializer

    def safely_get_queryset(self, queryset):
        params = self.request.GET.dict()
        queryset = queryset.filter(team_id=self.team.id)
        if params.get("issue_id"):
            queryset = queryset.filter(issue_id=params["issue_id"])
        return queryset


class ErrorTrackingIssueViewSet(TeamAndOrgViewSetMixin, ForbidDestroyModel, viewsets.ModelViewSet):
    scope_object = "INTERNAL"
    queryset = ErrorTrackingIssue.objects.with_first_seen().all()
    serializer_class = ErrorTrackingIssueSerializer

    def safely_get_queryset(self, queryset):
        return (
            queryset.select_related("assignment")
            .prefetch_related("external_issues__integration")
            .filter(team_id=self.team.id)
        )

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

                issue = (
                    ErrorTrackingIssue.objects.with_first_seen()
                    .select_related("assignment")
                    .prefetch_related("external_issues__integration")
                    .get(id=record.issue_id)
                )
                serializer = self.get_serializer(issue)
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

    def _get_issue_embeddings(self, issue_fingerprints: list[str], model_name: str, embedding_version: int):
        """Get embeddings along with model info for given fingerprints."""
        query = """
            SELECT DISTINCT embeddings
            FROM error_tracking_issue_fingerprint_embeddings
            WHERE team_id = %(team_id)s
            AND fingerprint IN %(fingerprints)s
            AND model_name = %(model_name)s
            AND embedding_version = %(embedding_version)s
        """

        issue_embeddings = sync_execute(
            query,
            {
                "team_id": self.team.pk,
                "fingerprints": issue_fingerprints,
                "model_name": model_name,
                "embedding_version": embedding_version,
            },
        )

        return issue_embeddings

    def _get_similar_embeddings(
        self,
        embedding_vector,
        model_name: str,
        embedding_version: int,
        issue_fingerprints: list[str],
        min_distance_threshold: float,
    ):
        """Get similar embeddings using cosine similarity."""
        query = """
              WITH %(target_embedding)s as target
            SELECT fingerprint, MIN(cosineDistance(embeddings, target)) as distance
              FROM error_tracking_issue_fingerprint_embeddings
             WHERE team_id = %(team_id)s
               AND model_name = %(model_name)s
               AND embedding_version = %(embedding_version)s
               AND fingerprint NOT IN %(fingerprints)s
               AND length(embeddings) = length(target)
             GROUP BY fingerprint
            HAVING distance <= %(min_distance_threshold)s
             ORDER BY distance ASC
             LIMIT 10;
        """

        similar_embeddings = sync_execute(
            query,
            {
                "team_id": self.team.pk,
                "target_embedding": embedding_vector,
                "model_name": model_name,
                "embedding_version": embedding_version,
                "fingerprints": issue_fingerprints,
                "min_distance_threshold": min_distance_threshold,
            },
        )
        return similar_embeddings

    def _get_embedding_configuration(self) -> tuple[float, str, int]:
        """Get embedding configuration from feature flag or return defaults."""
        min_distance_threshold = DEFAULT_MIN_DISTANCE_THRESHOLD
        model_name = DEFAULT_EMBEDDING_MODEL_NAME
        embedding_version = DEFAULT_EMBEDDING_VERSION

        # Try to get configuration from feature flag, fall back to defaults if not available
        try:
            team_id = str(self.team.id)
            config_json = posthoganalytics.get_feature_flag_payload("error-tracking-embedding-configuration", team_id)
            if config_json:
                config_payload = json.loads(config_json)

                # Validate that config_payload is a dict
                if config_payload and isinstance(config_payload, dict):
                    min_distance_threshold = config_payload.get(
                        "min_distance_threshold", DEFAULT_MIN_DISTANCE_THRESHOLD
                    )
                    model_name = config_payload.get("model_name", DEFAULT_EMBEDDING_MODEL_NAME)
                    embedding_version = config_payload.get("embedding_version", DEFAULT_EMBEDDING_VERSION)

                    # Validate types
                    if not isinstance(min_distance_threshold, (int | float)):
                        min_distance_threshold = DEFAULT_MIN_DISTANCE_THRESHOLD
                    if not isinstance(model_name, str):
                        model_name = DEFAULT_EMBEDDING_MODEL_NAME
                    if not isinstance(embedding_version, int):
                        embedding_version = DEFAULT_EMBEDDING_VERSION
        except Exception:
            # Fall back to defaults on any error (JSON parsing, network, etc.)
            min_distance_threshold = DEFAULT_MIN_DISTANCE_THRESHOLD
            model_name = DEFAULT_EMBEDDING_MODEL_NAME
            embedding_version = DEFAULT_EMBEDDING_VERSION

        return min_distance_threshold, model_name, embedding_version

    def _get_issues_library_data(
        self,
        fingerprints: list[str],
        earliest_timestamp: Optional[datetime] = None,
        latest_timestamp: Optional[datetime] = None,
    ) -> dict[str, str]:
        """Get library information for fingerprints from ClickHouse events."""
        params: dict[str, Any] = {}
        params["team_id"] = self.team.pk
        params["fingerprints"] = fingerprints

        timestamp_filter = ""
        if earliest_timestamp and latest_timestamp:
            timestamp_filter = "AND timestamp >= %(earliest_timestamp)s AND timestamp <= %(latest_timestamp)s"
            params["earliest_timestamp"] = earliest_timestamp
            params["latest_timestamp"] = latest_timestamp
        elif earliest_timestamp:
            timestamp_filter = "AND timestamp >= %(earliest_timestamp)s"
            params["earliest_timestamp"] = earliest_timestamp
        elif latest_timestamp:
            timestamp_filter = "AND timestamp <= %(latest_timestamp)s"
            params["latest_timestamp"] = latest_timestamp

        query = f"""
            SELECT mat_$exception_fingerprint, MIN(mat_$lib)
              FROM events
             WHERE team_id = %(team_id)s
               AND event = '$exception'
               AND mat_$exception_fingerprint IN %(fingerprints)s
               AND mat_$lib != ''
               {timestamp_filter}
             GROUP BY mat_$exception_fingerprint
        """

        results = sync_execute(
            query,
            params,
        )

        if not results or len(results) == 0:
            return {}
        # Return dict mapping fingerprint to library
        return dict(results)

    def _build_issue_to_library_mapping(
        self, issue_id_to_fingerprint: dict[str, str], fingerprint_to_library: dict[str, str]
    ) -> dict[str, str]:
        """Build mapping from issue_id to library using existing data."""
        if not fingerprint_to_library or len(fingerprint_to_library) == 0:
            return {}

        issue_to_library = {}
        # Map each issue to library data using fingerprints
        for issue_id, fingerprint in issue_id_to_fingerprint.items():
            if fingerprint in fingerprint_to_library:
                issue_to_library[issue_id] = fingerprint_to_library[fingerprint]
        return issue_to_library

    def _get_timestamp_range(self, issues) -> tuple[Optional[datetime], Optional[datetime]]:
        """Calculate timestamp range from issues for query optimization."""
        issue_timestamps = [issue.created_at for issue in issues if issue.created_at is not None]
        if issue_timestamps:
            earliest_timestamp = min(issue_timestamps)
            latest_timestamp = max(issue_timestamps)
        else:
            earliest_timestamp = None
            latest_timestamp = None
        return earliest_timestamp, latest_timestamp

    def _serialize_issues_to_similar_issues(self, issues, library_data: dict[str, str]):
        """Serialize ErrorTrackingIssue objects to similar issues format."""

        return [
            {
                "id": issue.id,
                "title": issue.name,
                "description": issue.description,
                **({} if str(issue.id) not in library_data else {"library": library_data[str(issue.id)]}),
            }
            for issue in issues
        ]

    def _process_embeddings_for_similarity(
        self,
        issue_embeddings,
        issue_fingerprints: list[str],
        min_distance_threshold: float,
        model_name: str,
        embedding_version: int,
    ) -> list[str]:
        """Process all embeddings to find similar fingerprints and return top 10 most similar."""
        similar_fingerprints = []

        # Search for similarities across all embeddings from the current issue
        for _, embedding_row in enumerate(issue_embeddings):
            embedding = embedding_row[0]  # Get the embedding vector

            # Search for similar embeddings using cosine similarity
            similar_embeddings = self._get_similar_embeddings(
                embedding, model_name, embedding_version, issue_fingerprints, min_distance_threshold
            )

            if not similar_embeddings or len(similar_embeddings) == 0:
                continue

            # Collect both fingerprint and distance
            for similar_embedding_row in similar_embeddings:
                fingerprint, distance = similar_embedding_row[0], similar_embedding_row[1]
                similar_fingerprints.append((fingerprint, distance))

        if not similar_fingerprints or len(similar_fingerprints) == 0:
            return []

        # Remove duplicates by fingerprint, keeping the best (smallest) distance for each
        fingerprint_best_distance: dict[str, float] = {}
        for fingerprint, distance in similar_fingerprints:
            if fingerprint not in fingerprint_best_distance or distance < fingerprint_best_distance[fingerprint]:
                fingerprint_best_distance[fingerprint] = distance

        if not fingerprint_best_distance or len(fingerprint_best_distance) == 0:
            return []

        # Sort by distance (ascending - smaller distance = more similar) and take top 10
        sorted_fingerprint_best_distance = sorted(fingerprint_best_distance.items(), key=lambda x: x[1])[:10]
        all_similar_fingerprints = [fingerprint for fingerprint, _ in sorted_fingerprint_best_distance]

        return all_similar_fingerprints

    @action(methods=["GET"], detail=True)
    def similar_issues(self, request: request.Request, **kwargs):
        issue_id = kwargs.get("pk")

        if not issue_id:
            return Response({"error": "issue_id is required"}, status=status.HTTP_400_BAD_REQUEST)

        issue_ids = [issue_id]
        issue_fingerprints = resolve_fingerprints_for_issues(team_id=self.team.pk, issue_ids=issue_ids)

        if not issue_fingerprints or len(issue_fingerprints) == 0:
            return Response([])

        # Get model configuration from feature flag
        min_distance_threshold, model_name, embedding_version = self._get_embedding_configuration()

        issue_embeddings = self._get_issue_embeddings(issue_fingerprints, model_name, embedding_version)

        if not issue_embeddings or len(issue_embeddings) == 0:
            return Response([])

        similar_fingerprints = self._process_embeddings_for_similarity(
            issue_embeddings, issue_fingerprints, min_distance_threshold, model_name, embedding_version
        )

        if not similar_fingerprints or len(similar_fingerprints) == 0:
            return Response([])

        # Get issue IDs that have these fingerprints
        fingerprint_issue_pairs = ErrorTrackingIssueFingerprintV2.objects.filter(
            team_id=self.team.pk, fingerprint__in=similar_fingerprints
        ).values_list("issue_id", "fingerprint")

        if not fingerprint_issue_pairs or len(fingerprint_issue_pairs) == 0:
            return Response([])

        # Create dict with issue_id as key and fingerprint as value
        issue_id_to_fingerprint = {str(issue_id): fingerprint for issue_id, fingerprint in fingerprint_issue_pairs}

        if not issue_id_to_fingerprint or len(issue_id_to_fingerprint) == 0:
            return Response([])

        # Get the actual issues from PostgreSQL
        issues = ErrorTrackingIssue.objects.filter(team=self.team, id__in=issue_id_to_fingerprint.keys())

        if not issues or len(issues) == 0:
            return Response([])

        # Calculate timestamp range from the issues to optimize the ClickHouse query
        earliest_timestamp, latest_timestamp = self._get_timestamp_range(issues)

        # Get library data for the similar fingerprints with timestamp range filter for performance
        fingerprint_to_library = self._get_issues_library_data(
            similar_fingerprints, earliest_timestamp, latest_timestamp
        )

        # Build mapping from issue_id to library using existing data
        issue_to_library = self._build_issue_to_library_mapping(issue_id_to_fingerprint, fingerprint_to_library)

        similar_issues = self._serialize_issues_to_similar_issues(issues, issue_to_library)
        return Response(similar_issues)

    @action(methods=["POST"], detail=True)
    def split(self, request, **kwargs):
        issue: ErrorTrackingIssue = self.get_object()
        fingerprints: list[str] = request.data.get("fingerprints", [])
        exclusive: bool = request.data.get("exclusive", True)
        issue.split(fingerprints=fingerprints, exclusive=exclusive)
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


class ErrorTrackingStackFrameSerializer(serializers.ModelSerializer):
    symbol_set_ref = serializers.CharField(source="symbol_set.ref", default=None)
    release = ErrorTrackingReleaseSerializer(source="symbol_set.release", read_only=True)

    class Meta:
        model = ErrorTrackingStackFrame
        fields = ["id", "raw_id", "created_at", "contents", "resolved", "context", "symbol_set_ref", "release"]


class ErrorTrackingStackFrameViewSet(TeamAndOrgViewSetMixin, ForbidDestroyModel, viewsets.ReadOnlyModelViewSet):
    scope_object = "INTERNAL"
    queryset = ErrorTrackingStackFrame.objects.all()
    serializer_class = ErrorTrackingStackFrameSerializer

    @action(methods=["POST"], detail=False)
    def batch_get(self, request, **kwargs):
        raw_ids = request.data.get("raw_ids", [])
        symbol_set = request.data.get("symbol_set", None)

        queryset = self.queryset.filter(team_id=self.team.id).select_related("symbol_set__release")

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

    # DEPRECATED: newer versions of the CLI use bulk uploads
    def create(self, request, *args, **kwargs) -> Response:
        # pull the symbol set reference from the query params
        chunk_id = request.query_params.get("chunk_id", None)
        multipart = request.query_params.get("multipart", False)
        release_id = request.query_params.get("release_id", None)

        posthoganalytics.capture(
            "error_tracking_symbol_set_deprecated_endpoint",
            distinct_id=request.user.pk,
            properties={"team_id": self.team.id, "endpoint": "create"},
        )

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
    # DEPRECATED: we should eventually remove this once everyone is using a new enough version of the CLI
    def start_upload(self, request, **kwargs):
        chunk_id = request.query_params.get("chunk_id", None)
        release_id = request.query_params.get("release_id", None)

        posthoganalytics.capture(
            "error_tracking_symbol_set_deprecated_endpoint",
            distinct_id=request.user.pk,
            properties={"team_id": self.team.id, "endpoint": "start_upload"},
        )

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
        chunk_ids: list[str] | None = request.data.get("chunk_ids")
        # Grab the release ID from the request json
        release_id: str | None = request.data.get("release_id", None)
        if not chunk_ids:
            return Response({"detail": "chunk_ids query parameter is required"}, status=status.HTTP_400_BAD_REQUEST)

        if not settings.OBJECT_STORAGE_ENABLED:
            raise ValidationError(
                code="object_storage_required",
                detail="Object storage must be available to allow source map uploads.",
            )

        chunk_id_url_map = bulk_create_symbol_sets(chunk_ids, self.team, release_id)

        return Response({"id_map": chunk_id_url_map}, status=status.HTTP_201_CREATED)

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

        symbol_set_ids = content_hashes.keys()
        symbol_sets = ErrorTrackingSymbolSet.objects.filter(team=self.team, id__in=symbol_set_ids)

        try:
            for symbol_set in symbol_sets:
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

                content_hash = content_hashes[str(symbol_set.id)]
                symbol_set.content_hash = content_hash
            ErrorTrackingSymbolSet.objects.bulk_update(symbol_sets, ["content_hash"])
        except Exception:
            for id in content_hashes.keys():
                # Try to clean up the symbol sets preemptively if the upload fails
                try:
                    symbol_set = ErrorTrackingSymbolSet.objects.all().filter(id=id, team=self.team).get()
                    symbol_set.delete()
                except Exception:
                    pass

            raise

        posthoganalytics.capture(
            "error_tracking_symbol_set_uploaded",
            distinct_id=request.user.pk,
            groups=groups(self.team.organization, self.team),
        )

        return Response({"success": True}, status=status.HTTP_201_CREATED)


class HasGetQueryset(Protocol):
    def get_queryset(self): ...


T = TypeVar("T", bound=HasGetQueryset)


class RuleReorderingMixin:
    @action(methods=["PATCH"], detail=False)
    def reorder(self: T, request, **kwargs):
        orders: dict[str, int] = request.data.get("orders", {})
        rules = self.get_queryset().filter(id__in=orders.keys())

        for rule in rules:
            rule.order_key = orders[str(rule.id)]

        self.get_queryset().bulk_update(rules, ["order_key"])

        return Response({"ok": True}, status=status.HTTP_204_NO_CONTENT)


class ErrorTrackingAssignmentRuleSerializer(serializers.ModelSerializer):
    assignee = serializers.SerializerMethodField()

    class Meta:
        model = ErrorTrackingAssignmentRule
        fields = ["id", "filters", "assignee", "order_key", "disabled_data"]
        read_only_fields = ["team_id"]

    def get_assignee(self, obj):
        if obj.user_id:
            return {"type": "user", "id": obj.user_id}
        elif obj.role_id:
            return {"type": "role", "id": obj.role_id}
        return None


class ErrorTrackingAssignmentRuleViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet, RuleReorderingMixin):
    scope_object = "error_tracking"
    queryset = ErrorTrackingAssignmentRule.objects.order_by("order_key").all()
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
        fields = ["id", "filters", "assignee", "order_key", "disabled_data"]
        read_only_fields = ["team_id"]

    def get_assignee(self, obj):
        if obj.user_id:
            return {"type": "user", "id": obj.user_id}
        elif obj.role_id:
            return {"type": "role", "id": obj.role_id}
        return None


class ErrorTrackingGroupingRuleViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet, RuleReorderingMixin):
    scope_object = "error_tracking"
    queryset = ErrorTrackingGroupingRule.objects.order_by("order_key").all()
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


class ErrorTrackingSuppressionRuleViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet, RuleReorderingMixin):
    scope_object = "error_tracking"
    queryset = ErrorTrackingSuppressionRule.objects.order_by("order_key").all()
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
        try:
            symbol_set = ErrorTrackingSymbolSet.objects.get(team=team, ref=chunk_id)
            if symbol_set.release is None:
                symbol_set.release = release
            elif symbol_set.release != release:
                raise ValidationError(f"Symbol set has already been uploaded for a different release")
            symbol_set.storage_ptr = storage_ptr
            symbol_set.content_hash = content_hash
            symbol_set.save()

        except ErrorTrackingSymbolSet.DoesNotExist:
            symbol_set = ErrorTrackingSymbolSet.objects.create(
                team=team,
                ref=chunk_id,
                release=release,
                storage_ptr=storage_ptr,
                content_hash=content_hash,
            )

        # Delete any existing frames associated with this symbol set
        ErrorTrackingStackFrame.objects.filter(team=team, symbol_set=symbol_set).delete()

        return symbol_set


def bulk_create_symbol_sets(
    chunk_ids: list[str],
    team: Team,
    release_id: str | None,
) -> dict[str, dict[str, str]]:
    release = create_release(team, release_id) if release_id else None

    id_url_map: dict[str, dict[str, str]] = {}

    with transaction.atomic():
        existing_symbol_sets = list(ErrorTrackingSymbolSet.objects.filter(team=team, ref__in=chunk_ids))
        existing_symbol_set_refs = [s.ref for s in existing_symbol_sets]
        missing_symbol_set_refs = list(set(chunk_ids) - set(existing_symbol_set_refs))

        symbol_sets_to_be_created = []
        for chunk_id in missing_symbol_set_refs:
            storage_ptr = generate_symbol_set_file_key()
            presigned_url = generate_symbol_set_upload_presigned_url(storage_ptr)
            id_url_map[chunk_id] = {"presigned_url": presigned_url}
            symbol_sets_to_be_created.append(
                ErrorTrackingSymbolSet(
                    team=team,
                    ref=chunk_id,
                    release=release,
                    storage_ptr=storage_ptr,
                )
            )

        # create missing symbol sets
        created_symbol_sets = ErrorTrackingSymbolSet.objects.bulk_create(symbol_sets_to_be_created)

        for symbol_set in created_symbol_sets:
            id_url_map[symbol_set.ref]["symbol_set_id"] = str(symbol_set.pk)

        # update existing symbol sets
        for symbol_set in existing_symbol_sets:
            if symbol_set.release is None:
                symbol_set.release = release
            elif symbol_set.release != release:
                raise ValidationError(f"Symbol set has already been uploaded for a different release")

            storage_ptr = generate_symbol_set_file_key()
            presigned_url = generate_symbol_set_upload_presigned_url(storage_ptr)
            id_url_map[symbol_set.ref] = {"presigned_url": presigned_url, "symbol_set_id": str(symbol_set.id)}
            symbol_set.storage_ptr = storage_ptr
            symbol_set.content_hash = None
        ErrorTrackingSymbolSet.objects.bulk_update(existing_symbol_sets, ["release", "storage_ptr", "content_hash"])

        # Delete any existing frames associated with this symbol set
        ErrorTrackingStackFrame.objects.filter(team=team, symbol_set__ref__in=chunk_ids).delete()

    return id_url_map


def create_release(team: Team, release_id: str) -> ErrorTrackingRelease | None:
    objects = ErrorTrackingRelease.objects.all().filter(team=team, id=release_id)
    if len(objects) < 1:
        raise ValueError(f"Unknown release: {release_id}")
    return objects[0]


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


def generate_symbol_set_upload_presigned_url(file_key: str):
    return object_storage.get_presigned_post(
        file_key=file_key,
        conditions=[["content-length-range", 0, ONE_HUNDRED_MEGABYTES]],
        expiration=PRESIGNED_MULTIPLE_UPLOAD_TIMEOUT,
    )


def generate_symbol_set_file_key():
    return f"{settings.OBJECT_STORAGE_ERROR_TRACKING_SOURCE_MAPS_FOLDER}/{str(uuid7())}"
