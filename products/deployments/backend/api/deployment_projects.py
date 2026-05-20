"""DRF wiring for the DeploymentProject viewset.

`DeploymentProject` is the top-level entity in the Deployments product —
one connected repo + its Cloudflare Pages target. Deployments are nested
under projects (see api/deployments.py).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.utils import timezone

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import filters, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.auth import OAuthAccessTokenAuthentication, PersonalAPIKeyAuthentication, SessionAuthentication
from posthog.models.integration import Integration
from posthog.permissions import APIScopePermission
from posthog.rbac.access_control_api_mixin import AccessControlViewSetMixin
from posthog.rbac.user_access_control import UserAccessControl, access_level_satisfied_for_resource

from ..access import has_deployments_access
from ..adapters import CloudflareError, get_cloudflare_adapter, get_github_adapter
from ..adapters.github import GitHubError, repo_url_from_full_name
from ..models import DeploymentProject
from ..serializers import (
    DeploymentProjectCreateSerializer,
    DeploymentProjectSerializer,
    DeploymentProjectWriteSerializer,
)
from ..services import provision_project
from ..services.detection import PackageManager, detect_config


class DeploymentsAccessPermission(BasePermission):
    """Gate the whole product behind the `deployments` feature flag."""

    message = "Deployments is not enabled for this team."

    def has_permission(self, request: Request, view: APIView) -> bool:
        team_id = getattr(view, "team_id", None)
        return has_deployments_access(request.user, team_id=team_id)


@dataclass(frozen=True)
class ResolvedRepositoryConfig:
    repo_url: str
    default_branch: str
    github_integration_id: int | None
    github_repo_id: int | None


@dataclass(frozen=True)
class RefreshedRepositoryState:
    repo_url: str
    default_branch: str
    commit_sha: str


def _can_view_integration(integration: Integration, *, user_access_control: UserAccessControl) -> bool:
    if user_access_control.check_access_level_for_resource("integration", required_level="viewer"):
        return user_access_control.check_access_level_for_object(integration, required_level="viewer")

    specific_access_level = user_access_control.specific_access_level_for_object(integration)
    return bool(
        specific_access_level
        and access_level_satisfied_for_resource("integration", specific_access_level, required_level="viewer")
    )


def _get_team_github_integration(
    *, team_id: int, integration_id: int, user_access_control: UserAccessControl
) -> Integration:
    integration = Integration.objects.filter(
        id=integration_id,
        team_id=team_id,
        kind=Integration.IntegrationKind.GITHUB.value,
    ).first()
    if integration is None or not _can_view_integration(integration, user_access_control=user_access_control):
        raise NotFound("GitHub integration not found for this project.")
    return integration


def _resolve_repository_config(
    data: dict[str, Any], *, team_id: int, user_access_control: UserAccessControl
) -> ResolvedRepositoryConfig:
    github_integration_id = data.get("github_integration_id")
    if github_integration_id is None:
        raise ValidationError({"github_integration_id": "This field is required."})

    github_repo_id = data.get("github_repo_id")
    if github_repo_id is None:
        raise ValidationError({"github_repo_id": "This field is required."})

    integration = _get_team_github_integration(
        team_id=team_id,
        integration_id=int(github_integration_id),
        user_access_control=user_access_control,
    )
    adapter = get_github_adapter()
    try:
        repository = adapter.get_repository_by_id(integration=integration, github_repo_id=int(github_repo_id))
        branch_name = str(data.get("default_branch") or repository.default_branch).strip() or repository.default_branch
        branch = adapter.get_branch(integration=integration, repo_full_name=repository.full_name, branch=branch_name)
    except GitHubError as err:
        raise ValidationError({"github": str(err)}) from err

    return ResolvedRepositoryConfig(
        repo_url=repository.html_url or repo_url_from_full_name(repository.full_name),
        default_branch=branch.name,
        github_integration_id=integration.id,
        github_repo_id=repository.id,
    )


class DetectConfigRequestSerializer(serializers.Serializer):
    """Inputs the `/detect/` endpoint needs to suggest a project config.

    Decouples detection from any one git provider — callers fetch
    `package.json` and the list of lockfiles however they like (GitHub
    raw content via the team's existing integration, a temporary clone,
    user-pasted JSON during early development) and pass them here.
    """

    package_json = serializers.JSONField(
        required=False,
        allow_null=True,
        help_text=(
            "Parsed contents of the repo's `package.json`. Pass null or omit if the "
            "repo doesn't have one — the response is then the plain-HTML fallback."
        ),
    )
    lockfiles = serializers.ListField(
        child=serializers.CharField(max_length=64),
        required=False,
        default=list,
        help_text=(
            "Filenames of package-manager lockfiles found in the repo root "
            '(e.g. ["pnpm-lock.yaml"]). Used to pick the package manager.'
        ),
    )


class DetectConfigResponseSerializer(serializers.Serializer):
    """Suggested project config. Every field is overridable in the connect-repo UI.

    `build_command`, `output_dir`, and `framework` map directly to the
    `DeploymentProject` model fields. `package_manager`, `install_command`,
    and `node_version` are informational hints — the model doesn't store
    them today, but the UI can display them so the user knows what the
    build worker will end up running.
    """

    package_manager = serializers.ChoiceField(
        choices=[(m.value, m.value) for m in PackageManager],
        help_text="Detected package manager from lockfile presence.",
    )
    install_command = serializers.CharField(
        allow_blank=True,
        help_text="Suggested install command, or empty when no install is needed.",
    )
    build_command = serializers.CharField(
        allow_blank=True,
        help_text="Suggested build command, or empty when no known framework matched.",
    )
    output_dir = serializers.CharField(help_text="Suggested output directory relative to repo root.")
    node_version = serializers.CharField(
        help_text="Suggested Node major version, parsed from `engines.node` or defaulted to 20.",
    )
    framework = serializers.CharField(
        allow_null=True,
        help_text=(
            "Detected framework hint (e.g. `nextjs`, `vite`, `astro`) to write into "
            "`DeploymentProject.framework`. Null when no framework matched — leaving the "
            "field null lets the build worker fall back to its own auto-detection."
        ),
    )


class DeploymentProjectRefreshResponseSerializer(serializers.Serializer):
    """Response shape for refreshing a deployment project's GitHub branch."""

    detail = serializers.CharField(help_text="Human-readable explanation of the refresh result.")
    repo_url = serializers.URLField(help_text="HTTPS URL of the connected GitHub repository.")
    default_branch = serializers.CharField(help_text="Branch checked by the refresh action.")
    commit_sha = serializers.CharField(help_text="Current GitHub HEAD SHA for default_branch.")


def _refresh_project_repository_state(
    project: DeploymentProject, *, user_access_control: UserAccessControl
) -> RefreshedRepositoryState:
    if project.github_integration_id is None or project.github_repo_id is None:
        raise ValidationError("Deployment project is not connected to a GitHub repository.")

    integration = _get_team_github_integration(
        team_id=project.team_id,
        integration_id=project.github_integration_id,
        user_access_control=user_access_control,
    )
    adapter = get_github_adapter()
    try:
        repository = adapter.get_repository_by_id(integration=integration, github_repo_id=project.github_repo_id)
        branch = adapter.get_branch(
            integration=integration,
            repo_full_name=repository.full_name,
            branch=project.default_branch,
        )
    except GitHubError as err:
        raise ValidationError({"github": str(err)}) from err

    repo_url = repository.html_url or repo_url_from_full_name(repository.full_name)
    if project.repo_url != repo_url:
        project.repo_url = repo_url
        project.save(update_fields=["repo_url", "updated_at"])

    return RefreshedRepositoryState(
        repo_url=repo_url,
        default_branch=branch.name,
        commit_sha=branch.sha,
    )


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
    search_fields = ["name", "slug", "repo_url", "default_branch"]
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
        request=DeploymentProjectCreateSerializer,
        responses={
            status.HTTP_201_CREATED: DeploymentProjectSerializer,
            status.HTTP_502_BAD_GATEWAY: OpenApiResponse(description="Cloudflare provisioning failed."),
        },
    )
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = DeploymentProjectCreateSerializer(data=request.data, context=self.get_serializer_context())
        serializer.is_valid(raise_exception=True)
        repository_config = _resolve_repository_config(
            serializer.validated_data,
            team_id=self.team_id,
            user_access_control=self.user_access_control,
        )
        try:
            project = provision_project.execute(
                provision_project.ProvisionInput(
                    team_id=self.team_id,
                    created_by_id=request.user.id if request.user.is_authenticated else None,
                    name=serializer.validated_data["name"],
                    slug=serializer.validated_data["slug"],
                    repo_url=repository_config.repo_url,
                    default_branch=repository_config.default_branch,
                    github_integration_id=repository_config.github_integration_id,
                    github_repo_id=repository_config.github_repo_id,
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

    def _save_with_repository_config(self, instance: DeploymentProject, serializer: Any) -> DeploymentProject:
        tracking_fields = {"github_integration_id", "github_repo_id", "default_branch"}
        save_kwargs: dict[str, Any] = {}
        if tracking_fields.intersection(serializer.validated_data):
            merged_data = {
                "default_branch": instance.default_branch,
                "github_integration_id": instance.github_integration_id,
                "github_repo_id": instance.github_repo_id,
            }
            merged_data.update(serializer.validated_data)
            repository_config = _resolve_repository_config(
                merged_data,
                team_id=self.team_id,
                user_access_control=self.user_access_control,
            )
            save_kwargs = {
                "repo_url": repository_config.repo_url,
                "default_branch": repository_config.default_branch,
                "github_integration_id": repository_config.github_integration_id,
                "github_repo_id": repository_config.github_repo_id,
            }
        return serializer.save(**save_kwargs)

    @extend_schema(
        request=DeploymentProjectWriteSerializer, responses={status.HTTP_200_OK: DeploymentProjectSerializer}
    )
    def update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        instance = self.get_object()
        serializer = DeploymentProjectWriteSerializer(
            instance,
            data=request.data,
            context=self.get_serializer_context(),
        )
        serializer.is_valid(raise_exception=True)
        project = self._save_with_repository_config(instance, serializer)
        return Response(self.get_serializer(project).data, status=status.HTTP_200_OK)

    @extend_schema(
        request=DeploymentProjectWriteSerializer, responses={status.HTTP_200_OK: DeploymentProjectSerializer}
    )
    def partial_update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        instance = self.get_object()
        serializer = DeploymentProjectWriteSerializer(
            instance,
            data=request.data,
            partial=True,
            context=self.get_serializer_context(),
        )
        serializer.is_valid(raise_exception=True)
        project = self._save_with_repository_config(instance, serializer)
        return Response(self.get_serializer(project).data, status=status.HTTP_200_OK)

    @extend_schema(
        request=None,
        responses={status.HTTP_200_OK: OpenApiResponse(response=DeploymentProjectRefreshResponseSerializer)},
        summary="Refresh a deployment project's GitHub branch",
    )
    @action(detail=True, methods=["post"])
    def refresh(self, request: Request, **kwargs: Any) -> Response:
        project = self.get_object()
        refreshed = _refresh_project_repository_state(project, user_access_control=self.user_access_control)
        return Response(
            DeploymentProjectRefreshResponseSerializer(
                {
                    "detail": "GitHub branch refreshed.",
                    "repo_url": refreshed.repo_url,
                    "default_branch": refreshed.default_branch,
                    "commit_sha": refreshed.commit_sha,
                }
            ).data,
            status=status.HTTP_200_OK,
        )

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

    @validated_request(
        request_serializer=DetectConfigRequestSerializer,
        responses={status.HTTP_200_OK: OpenApiResponse(response=DetectConfigResponseSerializer)},
        summary="Suggest project config from a repo's package.json and lockfiles",
        description=(
            "Pure inspection — no git access, no DB writes. The connect-repo "
            "UI calls this after fetching `package.json` (via the team's "
            "GitHub integration) and uses the response to prefill the form."
        ),
    )
    @action(detail=False, methods=["post"], pagination_class=None)
    def detect(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        package_json = request.validated_data.get("package_json")
        lockfiles = request.validated_data.get("lockfiles", [])
        detected = detect_config(package_json, lockfiles)
        return Response(
            DetectConfigResponseSerializer(
                {
                    "package_manager": detected.package_manager.value,
                    "install_command": detected.install_command,
                    "build_command": detected.build_command,
                    "output_dir": detected.output_dir,
                    "node_version": detected.node_version,
                    "framework": detected.framework,
                }
            ).data,
        )


class DeploymentProjectActionResponseSerializer(serializers.Serializer):
    """Generic action response shape (e.g. for 502 on Cloudflare failure)."""

    detail = serializers.CharField(help_text="Human-readable explanation of the response.")
