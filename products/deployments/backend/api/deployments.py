"""DRF wiring for the Deployments product.

Scaffold only. The serializer surfaces every model field with `help_text`
so generated TypeScript types and MCP tools have real descriptions, but
computed fields (`is_current`, `duration_seconds`) return hardcoded
placeholders. The viewset registers `list`, `retrieve`, and the
501-stubbed actions (`redeploy`, `rollback`, `refresh_preview`).
"""

from __future__ import annotations

from typing import Any

from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_field
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.rbac.access_control_api_mixin import AccessControlViewSetMixin

from ..access import has_deployments_access
from ..models import Deployment


class DeploymentsAccessPermission(BasePermission):
    """Gate the whole product behind the `deployments` feature flag.

    Returns 403 instead of 404 because we already have a flag-driven
    sidebar entry — there's no point pretending the URL doesn't exist
    once a request has reached this viewset.
    """

    message = "Deployments is not enabled for this team."

    def has_permission(self, request: Request, view: APIView) -> bool:
        team_id = getattr(view, "team_id", None)
        return has_deployments_access(request.user, team_id=team_id)


class DeploymentSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(read_only=True, help_text="Unique identifier for the deployment.")
    status = serializers.ChoiceField(
        choices=Deployment.Status.choices,
        help_text=(
            "Current pipeline stage for the deployment. Valid values: "
            "queued, initializing, building, ready, error, cancelled."
        ),
    )
    started_at = serializers.DateTimeField(
        allow_null=True,
        required=False,
        help_text="Timestamp when the pipeline started building. Null while still queued.",
    )
    finished_at = serializers.DateTimeField(
        allow_null=True,
        required=False,
        help_text="Timestamp when the pipeline finished (regardless of outcome). Null while still running.",
    )
    created_at = serializers.DateTimeField(
        read_only=True,
        help_text="Timestamp when the deployment row was created.",
    )

    commit_sha = serializers.CharField(
        allow_blank=True,
        required=False,
        max_length=64,
        help_text="Git commit SHA the deployment was built from. Empty for non-git triggers.",
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
        help_text="Email address of the commit author.",
    )

    repo_url = serializers.URLField(
        allow_blank=True,
        required=False,
        max_length=1024,
        help_text="HTTPS URL of the source repository this deployment came from.",
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
        help_text="Public URL where the built site is served once the deployment is ready.",
    )
    preview_image_url = serializers.URLField(
        allow_blank=True,
        required=False,
        max_length=1024,
        help_text="URL of a screenshot capture of the deployed site, used in the list view.",
    )

    triggered_by_deployment = serializers.PrimaryKeyRelatedField(
        read_only=True,
        allow_null=True,
        help_text="The deployment this one was triggered from (e.g. for rollbacks/redeploys).",
    )
    trigger_kind = serializers.ChoiceField(
        choices=Deployment.TriggerKind.choices,
        help_text="What caused this deployment to start. One of: git, redeploy, rollback, seed.",
    )

    is_current = serializers.SerializerMethodField(
        help_text="Whether this deployment is the team's currently-serving production deployment.",
    )
    duration_seconds = serializers.SerializerMethodField(
        help_text="Build duration in seconds (finished_at - started_at). 0 while still running.",
    )

    class Meta:
        model = Deployment
        fields = [
            "id",
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
            "trigger_kind",
            "is_current",
            "duration_seconds",
        ]
        # SerializerMethodField is always read-only in DRF, so listing
        # is_current / duration_seconds here would be redundant.
        read_only_fields = ["id", "created_at", "triggered_by_deployment"]

    # TODO(deployments-v1): replace with a real `Subquery`/annotation that
    # marks the most recent `READY` deployment per team as current.
    @extend_schema_field(serializers.BooleanField())
    def get_is_current(self, obj: Deployment) -> bool:
        return False

    # TODO(deployments-v1): replace with `(finished_at - started_at).total_seconds()`
    # once the mock pipeline starts writing timestamps.
    @extend_schema_field(serializers.IntegerField())
    def get_duration_seconds(self, obj: Deployment) -> int:
        return 0


class DeploymentActionResponseSerializer(serializers.Serializer):
    """Response shape for the redeploy/rollback/refresh-preview stubs."""

    detail = serializers.CharField(help_text="Human-readable explanation of the stub response.")


@extend_schema(tags=["deployments"])
class DeploymentViewSet(
    TeamAndOrgViewSetMixin,
    AccessControlViewSetMixin,
    viewsets.ReadOnlyModelViewSet,
):
    """Read-only viewset for the Deployments product.

    `list` and `retrieve` are wired against the model queryset. The
    `@action` stubs (`redeploy`, `rollback`, `refresh_preview`) intentionally
    return 501 — they exist so OpenAPI / MCP can discover the surface area
    while behavior lands in follow-up commits.
    """

    scope_object = "deployment"
    # The TeamAndOrgViewSetMixin appends class-level permission_classes to its
    # mandatory set (IsAuthenticated + APIScopePermission + AccessControlPermission
    # + TeamMemberAccessPermission), so we get the feature-flag gate on top of
    # all the standard checks without overriding get_permissions (which the mixin
    # protects via __init_subclass__).
    permission_classes = [DeploymentsAccessPermission]
    serializer_class = DeploymentSerializer
    # Use `all_teams` (the unscoped sibling manager) at class-definition
    # time — `objects` is fail-closed and would raise without a team
    # context. `safely_get_queryset` re-applies the team filter explicitly.
    queryset = Deployment.all_teams.all()

    def safely_get_queryset(self, queryset: Any) -> Any:
        # TODO(deployments-v1): wire filters (status, author, search) once
        # `DeploymentsFilters` is implemented on the frontend.
        return queryset.filter(team_id=self.team_id)

    @extend_schema(
        request=None,
        responses={status.HTTP_501_NOT_IMPLEMENTED: OpenApiResponse(response=DeploymentActionResponseSerializer)},
    )
    @action(detail=True, methods=["post"])
    def redeploy(self, request: Request, **kwargs: Any) -> Response:
        # TODO(deployments-v1): enqueue a redeploy by cloning this deployment's commit_sha.
        return Response(
            DeploymentActionResponseSerializer({"detail": "Redeploy is not implemented yet."}).data,
            status=status.HTTP_501_NOT_IMPLEMENTED,
        )

    @extend_schema(
        request=None,
        responses={status.HTTP_501_NOT_IMPLEMENTED: OpenApiResponse(response=DeploymentActionResponseSerializer)},
    )
    @action(detail=True, methods=["post"])
    def rollback(self, request: Request, **kwargs: Any) -> Response:
        # TODO(deployments-v1): make this deployment the currently-serving one,
        # creating a new `rollback`-trigger deployment that points at it.
        return Response(
            DeploymentActionResponseSerializer({"detail": "Rollback is not implemented yet."}).data,
            status=status.HTTP_501_NOT_IMPLEMENTED,
        )

    @extend_schema(
        request=None,
        responses={status.HTTP_501_NOT_IMPLEMENTED: OpenApiResponse(response=DeploymentActionResponseSerializer)},
    )
    @action(detail=True, methods=["post"], url_path="refresh-preview")
    def refresh_preview(self, request: Request, **kwargs: Any) -> Response:
        # TODO(deployments-v1): re-capture `preview_image_url` via the
        # microlink-backed `preview_capture` service.
        return Response(
            DeploymentActionResponseSerializer({"detail": "Refresh preview is not implemented yet."}).data,
            status=status.HTTP_501_NOT_IMPLEMENTED,
        )
