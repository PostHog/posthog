"""Serializer for Deployment.

`is_current` reads an annotated `Exists` subquery — see DeploymentViewSet
for the queryset annotation. `duration_seconds` is a SerializerMethodField
because it depends on two fields that may be null mid-build.
"""

from __future__ import annotations

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from ..models import Deployment, DeploymentProject


class DeploymentSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(read_only=True, help_text="Unique identifier for the deployment.")
    project: serializers.PrimaryKeyRelatedField = serializers.PrimaryKeyRelatedField(  # ty: ignore[invalid-assignment]
        read_only=True,
        help_text="The deployment project this deployment belongs to.",
    )

    status = serializers.ChoiceField(
        choices=Deployment.Status.choices,
        help_text=("Current pipeline stage. Valid values: queued, initializing, building, ready, error, cancelled."),
    )
    started_at = serializers.DateTimeField(
        allow_null=True,
        required=False,
        help_text="When the pipeline started building. Null while still queued.",
    )
    finished_at = serializers.DateTimeField(
        allow_null=True,
        required=False,
        help_text="When the pipeline finished (regardless of outcome). Null while still running.",
    )
    created_at = serializers.DateTimeField(
        read_only=True,
        help_text="When the deployment row was created (~ queued_at).",
    )

    commit_sha = serializers.CharField(
        allow_blank=True,
        required=False,
        max_length=64,
        help_text="Git commit SHA the deployment was built from.",
    )
    commit_message = serializers.CharField(
        allow_blank=True,
        required=False,
        help_text="Commit message associated with the commit SHA.",
    )
    commit_author_name = serializers.CharField(
        allow_blank=True,
        required=False,
        max_length=255,
        help_text="Display name of the commit author.",
    )
    commit_author_email = serializers.CharField(
        allow_blank=True,
        required=False,
        max_length=255,
        help_text="Email address of the commit author. Used by the Author filter on the list page.",
    )

    repo_url = serializers.URLField(
        allow_blank=True,
        required=False,
        max_length=1024,
        help_text="HTTPS URL of the source repository. Captured at deploy time.",
    )
    branch = serializers.CharField(
        allow_blank=True,
        required=False,
        max_length=255,
        help_text="Source branch the deployment was built from.",
    )

    deployment_url = serializers.URLField(
        allow_blank=True,
        required=False,
        max_length=1024,
        help_text="Public URL serving the built site once ready.",
    )
    preview_image_url = serializers.URLField(
        allow_blank=True,
        required=False,
        max_length=1024,
        help_text="URL of the captured site screenshot, used in the list/card view.",
    )

    triggered_by_deployment: serializers.PrimaryKeyRelatedField = serializers.PrimaryKeyRelatedField(  # ty: ignore[invalid-assignment]
        read_only=True,
        allow_null=True,
        help_text="The deployment this one was triggered from (for rollbacks and redeploys).",
    )
    triggered_by_user_id = serializers.IntegerField(
        read_only=True,
        allow_null=True,
        help_text="Posthog user id of the user who clicked Deploy/Redeploy/Rollback. Null for git-triggered or seed rows.",
    )
    trigger_kind = serializers.ChoiceField(
        choices=Deployment.TriggerKind.choices,
        help_text="What caused this deployment to start: manual | git | redeploy | rollback | seed.",
    )

    error_message = serializers.CharField(
        read_only=True,
        help_text="Failure detail set when status=error. Empty for successful or in-flight deployments.",
    )
    error_step = serializers.ChoiceField(
        choices=Deployment.ErrorStep.choices,
        required=False,
        allow_blank=True,
        help_text="Build step that failed: dispatch | clone | install | build | publish. Empty when status != error.",
    )

    cloudflare_deployment_id = serializers.CharField(
        read_only=True,
        help_text="Cloudflare Pages deployment id, set once the publish step succeeds.",
    )
    temporal_workflow_id = serializers.CharField(
        read_only=True,
        help_text="Temporal workflow id for this build. Used for cancellation signalling.",
    )

    is_current = serializers.SerializerMethodField(
        help_text="True if this deployment is currently serving production traffic for its project.",
    )
    duration_seconds = serializers.SerializerMethodField(
        help_text="Build duration in seconds (finished_at - started_at). 0 while still running.",
    )

    class Meta:
        model = Deployment
        fields = [
            "id",
            "project",
            "status",
            "started_at",
            "finished_at",
            "created_at",
            "commit_sha",
            "commit_message",
            "commit_author_name",
            "commit_author_email",
            "repo_url",
            "branch",
            "deployment_url",
            "preview_image_url",
            "triggered_by_deployment",
            "triggered_by_user_id",
            "trigger_kind",
            "error_message",
            "error_step",
            "cloudflare_deployment_id",
            "temporal_workflow_id",
            "is_current",
            "duration_seconds",
        ]
        # SerializerMethodField is implicitly read-only.
        read_only_fields = [
            "id",
            "project",
            "created_at",
            "triggered_by_deployment",
            "triggered_by_user_id",
            "error_message",
            "cloudflare_deployment_id",
            "temporal_workflow_id",
        ]

    @extend_schema_field(serializers.BooleanField())
    def get_is_current(self, obj: Deployment) -> bool:
        # The list viewset annotates rows with `is_current` via Exists()
        # for O(1) per-row reads. When the serializer is used outside that
        # path (refresh_preview, detail actions, admin), fall back to a
        # direct DB lookup so the field stays accurate.
        annotated = getattr(obj, "is_current", None)
        if annotated is not None:
            return bool(annotated)
        return DeploymentProject.all_teams.filter(current_deployment_id=obj.pk).exists()

    @extend_schema_field(serializers.IntegerField())
    def get_duration_seconds(self, obj: Deployment) -> int:
        if obj.started_at is None or obj.finished_at is None:
            return 0
        return int((obj.finished_at - obj.started_at).total_seconds())


class DeploymentCreateInputSerializer(serializers.Serializer):
    """Body of POST /api/projects/{}/deployment_projects/{}/deployments/."""

    commit_sha = serializers.CharField(
        max_length=64,
        required=False,
        allow_blank=True,
        help_text="Optional commit SHA. If omitted, the build worker resolves HEAD of `branch` (or the project's default_branch).",
    )
    branch = serializers.CharField(
        max_length=255,
        required=False,
        allow_blank=True,
        help_text="Optional branch override. If omitted, uses the project's `default_branch`.",
    )


class DeploymentActionResponseSerializer(serializers.Serializer):
    """Response shape for one-off action endpoints (cancel, refresh_preview)."""

    detail = serializers.CharField(help_text="Short human-readable confirmation message.")


class DeploymentConflictResponseSerializer(serializers.Serializer):
    """Response shape returned with HTTP 409 when an active deploy exists."""

    detail = serializers.CharField(help_text="Reason for the conflict.")
    active_deployment_id = serializers.UUIDField(
        help_text="The deployment currently in-flight for the project. Frontend can poll this id.",
    )


class DeploymentLogEntrySerializer(serializers.Serializer):
    """One line of build output emitted by the build worker as a `$log` event."""

    timestamp = serializers.DateTimeField(help_text="When the line was emitted by the build worker.")
    level = serializers.CharField(
        allow_null=True,
        help_text='Log level: "info" | "warn" | "error". Null if the event did not carry one.',
    )
    step = serializers.CharField(
        allow_null=True,
        help_text='Pipeline step: "clone" | "install" | "build" | "publish". Null if the event did not carry one.',
    )
    line = serializers.CharField(
        allow_null=True,
        help_text="The log line itself (a single line of stdout or stderr).",
    )
    exit_code = serializers.IntegerField(
        allow_null=True,
        help_text="Set on the last line of a step; null on all other lines.",
    )


class DeploymentLogsResponseSerializer(serializers.Serializer):
    """Response shape for GET /deployments/{id}/logs/."""

    results = DeploymentLogEntrySerializer(many=True, help_text="Log lines for the deployment, oldest first.")
    has_more = serializers.BooleanField(
        help_text="True if the row limit was hit and older lines may exist beyond this page.",
    )
    row_limit = serializers.IntegerField(help_text="The hard cap applied by the server.")
