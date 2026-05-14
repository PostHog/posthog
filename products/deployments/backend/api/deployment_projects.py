"""DRF wiring for the DeploymentProject viewset.

`DeploymentProject` is the top-level entity in the Deployments product —
one connected repo + its Cloudflare Pages target. Deployments are nested
under projects (see api/deployments.py).
"""

from __future__ import annotations

from typing import Any

from django.utils import timezone

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import filters, serializers, status, viewsets
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.auth import OAuthAccessTokenAuthentication, PersonalAPIKeyAuthentication, SessionAuthentication
from posthog.permissions import APIScopePermission
from posthog.rbac.access_control_api_mixin import AccessControlViewSetMixin

from ..access import has_deployments_access
from ..adapters import CloudflareError, get_cloudflare_adapter
from ..models import DeploymentProject
from ..serializers import DeploymentProjectSerializer
from ..services import provision_project


class DeploymentsAccessPermission(BasePermission):
    """Gate the whole product behind the `deployments` feature flag."""

    message = "Deployments is not enabled for this team."

    def has_permission(self, request: Request, view: APIView) -> bool:
        team_id = getattr(view, "team_id", None)
        return has_deployments_access(request.user, team_id=team_id)


@extend_schema(tags=["deployments"])
class DeploymentProjectViewSet(
    TeamAndOrgViewSetMixin,
    AccessControlViewSetMixin,
    viewsets.ModelViewSet,
):
    """CRUD for DeploymentProject (the connected-repo + hosting-target entity).

    Create-time provisioning calls Cloudflare BEFORE writing the DB row
    (see services/provision_project.py for the rationale). Delete is a
    soft-delete; Cloudflare-side cleanup is deferred to a periodic Celery
    task.
    """

    scope_object = "deployment"
    authentication_classes = [
        SessionAuthentication,
        PersonalAPIKeyAuthentication,
        OAuthAccessTokenAuthentication,
    ]
    permission_classes = [IsAuthenticated, APIScopePermission, DeploymentsAccessPermission]
    serializer_class = DeploymentProjectSerializer
    # all_teams is the unscoped sibling manager — `objects` is fail-closed
    # and would raise without a team context at class-definition time.
    queryset = DeploymentProject.all_teams.all()
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["name", "slug", "repo_url"]
    ordering_fields = ["created_at", "updated_at", "name"]
    ordering = ["-created_at"]
    # URL parent `project_id` is the PostHog team_id (project/team alias).
    # Rewrite to the model field so the framework's parent-lookup filter
    # finds rows. Without this the router would try to filter `team`,
    # which doesn't exist on ProductTeamModel.
    filter_rewrite_rules = {"project_id": "team_id"}

    def safely_get_queryset(self, queryset: Any) -> Any:
        # Default queryset hides soft-deleted projects.
        return queryset.filter(team_id=self.team_id).exclude(deleted=True)

    @extend_schema(
        request=DeploymentProjectSerializer,
        responses={
            status.HTTP_201_CREATED: DeploymentProjectSerializer,
            status.HTTP_502_BAD_GATEWAY: OpenApiResponse(description="Cloudflare provisioning failed."),
        },
    )
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            project = provision_project.execute(
                provision_project.ProvisionInput(
                    team_id=self.team_id,
                    created_by_id=request.user.id if request.user.is_authenticated else None,
                    name=serializer.validated_data["name"],
                    slug=serializer.validated_data["slug"],
                    repo_url=serializer.validated_data["repo_url"],
                    default_branch=serializer.validated_data.get("default_branch", "main"),
                    github_integration_id=serializer.validated_data.get("github_integration_id"),
                    build_command=serializer.validated_data.get("build_command"),
                    output_dir=serializer.validated_data.get("output_dir", "dist"),
                    framework=serializer.validated_data.get("framework"),
                    inject_posthog_snippet=serializer.validated_data.get("inject_posthog_snippet", False),
                ),
                cloudflare=get_cloudflare_adapter(),
            )
        except CloudflareError as exc:
            return Response(
                {"detail": f"Cloudflare provisioning failed: {exc}"},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        return Response(self.get_serializer(project).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=DeploymentProjectSerializer, responses={status.HTTP_200_OK: DeploymentProjectSerializer})
    def partial_update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().partial_update(request, *args, **kwargs)

    @extend_schema(responses={status.HTTP_204_NO_CONTENT: None})
    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        # Soft-delete: mark deleted=True / deleted_at=now() rather than removing
        # the row. The slug remains reserved (the partial unique constraint
        # excludes deleted rows so a new project can reuse the slug after
        # soft-delete, but anyone with the old URL still gets a 404).
        instance = self.get_object()
        instance.deleted = True
        instance.deleted_at = timezone.now()
        instance.save(update_fields=["deleted", "deleted_at", "updated_at"])
        return Response(status=status.HTTP_204_NO_CONTENT)


class DeploymentProjectActionResponseSerializer(serializers.Serializer):
    """Generic action response shape (e.g. for 502 on Cloudflare failure)."""

    detail = serializers.CharField(help_text="Human-readable explanation of the response.")
