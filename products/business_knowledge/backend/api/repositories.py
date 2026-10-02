from typing import Any, cast

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import exceptions
from rest_framework.decorators import action
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.viewsets import ViewSet

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.user import User
from posthog.permissions import APIScopePermission, PostHogFeatureFlagPermission
from posthog.rate_limit import BurstRateThrottle, SustainedRateThrottle

from products.business_knowledge.backend.github_repos import (
    GITHUB_REPOS_FLAG,
    GithubReposError,
    RepositoryFile,
    RepositorySearchOutcome,
    connect_github,
    connection_status,
    disconnect_github,
    read_repository_file,
    search_repositories,
    select_github_repos,
)

from .repository_serializers import (
    RepositoryConnectionSerializer,
    RepositoryConnectSerializer,
    RepositoryFileQuerySerializer,
    RepositoryFileSerializer,
    RepositorySearchQuerySerializer,
    RepositorySearchResponseSerializer,
    RepositorySelectionSerializer,
)

_READ_ACTIONS = frozenset({"status", "search", "read_file"})
_WRITE_ACTIONS = frozenset({"connect", "disconnect", "select"})


class BusinessKnowledgeGithubReposPermission(BasePermission):
    """Both the product flag and the repository flag. The stock checker returns on the first hit."""

    def has_permission(self, request: Request, view: Any) -> bool:
        checker = PostHogFeatureFlagPermission()
        for flag in ("product-business-knowledge", GITHUB_REPOS_FLAG):
            view.posthog_feature_flag = flag
            if not checker.has_permission(request, view):
                self.message = checker.message
                code = getattr(checker, "code", None)
                if code is not None:
                    self.code = code
                return False
        return True


class BusinessKnowledgeRepositoriesViewSet(TeamAndOrgViewSetMixin, ViewSet):
    scope_object = "business_knowledge"
    # Plain ViewSet: object permissions never run, so resource-level access is checked here.
    requires_resource_level_access = True
    permission_classes = [IsAuthenticated, APIScopePermission, BusinessKnowledgeGithubReposPermission]
    posthog_feature_flag = GITHUB_REPOS_FLAG
    throttle_classes = [BurstRateThrottle, SustainedRateThrottle]
    pagination_class = None

    def dangerously_get_required_scopes(self, request: Request, view: Any) -> list[str] | None:
        if self.action in _WRITE_ACTIONS:
            return ["business_knowledge:write"]
        if self.action in _READ_ACTIONS:
            return ["business_knowledge:read"]
        return None

    @validated_request(
        query_serializer=None,
        responses={200: OpenApiResponse(response=RepositoryConnectionSerializer)},
        summary="Get the GitHub repositories connected to business knowledge",
        description="The GitHub installation and the repositories this environment allows business knowledge to read.",
        operation_id="business_knowledge_repositories_status_retrieve",
    )
    @action(
        detail=False,
        methods=["GET"],
        url_path="status",
        pagination_class=None,
        required_scopes=["business_knowledge:read"],
    )
    def status(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        return Response(RepositoryConnectionSerializer(connection_status(self.team)).data)

    @validated_request(
        request_serializer=RepositoryConnectSerializer,
        responses={200: OpenApiResponse(response=RepositoryConnectionSerializer)},
        summary="Connect a GitHub installation to business knowledge",
        description="Stores the installation for this environment. Switching installations clears the selected repositories.",
        operation_id="business_knowledge_repositories_connect_create",
    )
    @action(
        detail=False,
        methods=["POST"],
        url_path="connect",
        pagination_class=None,
        required_scopes=["business_knowledge:write"],
    )
    def connect(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        return Response(
            RepositoryConnectionSerializer(connect_github(self.team, request.validated_data["integration_id"])).data
        )

    @extend_schema(
        request=None,
        responses={200: OpenApiResponse(response=RepositoryConnectionSerializer)},
        summary="Disconnect GitHub from business knowledge",
        description="Clears the installation and the selected repositories for this environment.",
        operation_id="business_knowledge_repositories_disconnect_create",
    )
    @action(
        detail=False,
        methods=["POST"],
        url_path="disconnect",
        pagination_class=None,
        required_scopes=["business_knowledge:write"],
    )
    def disconnect(self, request: Request, **kwargs: Any) -> Response:
        return Response(RepositoryConnectionSerializer(disconnect_github(self.team)).data)

    @validated_request(
        request_serializer=RepositorySelectionSerializer,
        responses={200: OpenApiResponse(response=RepositoryConnectionSerializer)},
        summary="Replace the repositories business knowledge can read",
        description="Every name must be a repository the connected installation can see. Names are stored lowercased.",
        operation_id="business_knowledge_repositories_selection_create",
    )
    @action(
        detail=False,
        methods=["POST"],
        url_path="selection",
        pagination_class=None,
        required_scopes=["business_knowledge:write"],
    )
    def select(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        return Response(
            RepositoryConnectionSerializer(select_github_repos(self.team, request.validated_data["repos"])).data
        )

    @validated_request(
        query_serializer=RepositorySearchQuerySerializer,
        responses={200: OpenApiResponse(response=RepositorySearchResponseSerializer)},
        summary="Search selected GitHub repositories",
        description=(
            "Matches file paths and README text in the cached default-branch file list. "
            "Pass file names or identifiers, then read a file. Does not search file contents."
        ),
        operation_id="business_knowledge_repositories_search",
    )
    @action(
        detail=False,
        methods=["GET"],
        url_path="search",
        pagination_class=None,
        required_scopes=["business_knowledge:read"],
    )
    def search(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        outcome = search_repositories(
            self.team,
            cast(User, request.user),
            request.validated_query_data["query"],
            request.validated_query_data.get("repo") or None,
        )
        return Response(RepositorySearchResponseSerializer(_search_payload(outcome)).data)

    @validated_request(
        query_serializer=RepositoryFileQuerySerializer,
        responses={200: OpenApiResponse(response=RepositoryFileSerializer)},
        summary="Read a file from a selected GitHub repository",
        description=(
            "Reads one file whose path is in the cached file list, at the cached commit. "
            "The path must come from the repository search."
        ),
        operation_id="business_knowledge_repositories_file_retrieve",
    )
    @action(
        detail=False,
        methods=["GET"],
        url_path="file",
        pagination_class=None,
        required_scopes=["business_knowledge:read"],
    )
    def read_file(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        loaded = read_repository_file(
            self.team,
            cast(User, request.user),
            request.validated_query_data["repo"],
            request.validated_query_data["path"],
        )
        return Response(RepositoryFileSerializer(_file_payload(loaded)).data)

    def handle_exception(self, exc: Exception) -> Response:
        if isinstance(exc, GithubReposError):
            exc = exceptions.ValidationError(str(exc))
        return super().handle_exception(exc)


def _search_payload(outcome: RepositorySearchOutcome) -> dict[str, Any]:
    return {
        "results": [
            {"repo": hit.repo, "path": hit.path, "url": hit.url, "kind": hit.kind, "excerpt": hit.excerpt}
            for hit in outcome.hits
        ],
        "repositories": [
            {"repo": state.repo, "tree_truncated": state.tree_truncated, "cache_status": state.cache_status}
            for state in outcome.repositories
        ],
    }


def _file_payload(loaded: RepositoryFile) -> dict[str, Any]:
    return {
        "repo": loaded.repo,
        "path": loaded.path,
        "url": loaded.url,
        "content": loaded.content,
        "truncated": loaded.truncated,
    }
