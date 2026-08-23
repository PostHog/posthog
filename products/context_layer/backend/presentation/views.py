from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied, Throttled, ValidationError
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.oauth_provenance import INTERNAL_RUN_SCOPE, get_oauth_access_token
from posthog.permissions import APIScopePermission, PostHogFeatureFlagPermission

from products.context_layer.backend.facade import api as facade
from products.context_layer.backend.presentation.serializers import (
    CommitBundleSerializer,
    ContextLayerStatusSerializer,
    HeadConflictSerializer,
    LintErrorSerializer,
    WikiExportSerializer,
    WikiHealthReportSerializer,
    WikiPageSerializer,
    WikiPageWriteSerializer,
    WikiTreeSerializer,
)


def _assert_no_private_projects(organization_id) -> None:  # noqa: ANN001
    """The wiki is org-readable, so it goes dark the moment any project is private.

    Enablement refuses orgs with private projects, but privacy can arrive later;
    imported context must not stay readable to members the project now excludes.
    Re-enabling access means removing the project restriction (or, later,
    per-project partitioning).
    """
    if facade.organization_has_private_projects(organization_id):
        raise PermissionDenied(
            "This organization now has private projects, so its context wiki is unavailable. "
            "The context layer does not support private projects yet.",
            code="private_projects",
        )


def _store_error_response(error: facade.ContextLayerStoreError) -> Response:
    """One mapping from store errors to HTTP for every action, so new writers
    added in later layers cannot drift from this contract."""
    if isinstance(error, facade.RepoNotFoundError):
        raise NotFound("The context layer is not enabled for this organization.") from error
    if isinstance(error, facade.InvalidPagePathError):
        raise ValidationError(str(error)) from error
    if isinstance(error, facade.RepoLockUnavailableError):
        raise Throttled(detail=str(error))
    if isinstance(error, facade.PageNotFoundError):
        raise NotFound(str(error)) from error
    if isinstance(error, facade.HeadConflictError):
        return Response(
            {
                "detail": "The wiki changed since this edit was based; re-read and retry.",
                "current_head": error.current_head,
            },
            status=status.HTTP_409_CONFLICT,
        )
    if isinstance(error, facade.BundleConflictError):
        return Response({"detail": str(error)}, status=status.HTTP_409_CONFLICT)
    if isinstance(error, facade.LintFailedError):
        return Response(
            {"detail": "The change violates the wiki structure.", "errors": error.errors},
            status=status.HTTP_400_BAD_REQUEST,
        )
    raise error


def _read_page(organization_id, request: Request) -> Response:  # noqa: ANN001
    _assert_no_private_projects(organization_id)
    try:
        wiki_page = facade.get_page(organization_id, request.query_params.get("path", ""))
    except facade.ContextLayerStoreError as error:
        return _store_error_response(error)
    return Response(WikiPageSerializer(wiki_page).data)


def _write_page(organization_id, request: Request) -> Response:  # noqa: ANN001
    _assert_no_private_projects(organization_id)
    serializer = WikiPageWriteSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    user = request.user
    author = (
        facade.CommitAuthor(name=user.first_name or user.email, email=user.email)
        if user and user.is_authenticated
        else None
    )
    try:
        head_sha = facade.write_page(
            organization_id,
            path=serializer.validated_data["path"],
            content=serializer.validated_data["content"],
            base_head=serializer.validated_data.get("base_head"),
            author=author,
        )
    except facade.ContextLayerStoreError as error:
        return _store_error_response(error)
    return Response(ContextLayerStatusSerializer({"head_sha": head_sha}).data)


def _land_commits(organization_id, request: Request) -> Response:  # noqa: ANN001
    _assert_no_private_projects(organization_id)
    serializer = CommitBundleSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    bundle_bytes = serializer.validated_data["bundle"].read()
    try:
        head_sha = facade.land_commit_bundle(
            organization_id, bundle_bytes, summary=serializer.validated_data.get("summary") or None
        )
    except facade.ContextLayerStoreError as error:
        return _store_error_response(error)
    return Response(ContextLayerStatusSerializer({"head_sha": head_sha}).data)


@extend_schema(tags=["context_layer"])
class ContextLayerViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """The organization's context wiki: a git repo of Markdown pages hosted by PostHog."""

    # No authentication_classes override: the mixin already appends PostHog's
    # session/PAT/OAuth authenticators, and DRF's stock SessionAuthentication
    # would run first and skip enforce_two_factor.
    # The flag is the rollout boundary: the whole surface stays off until the
    # organization opts into `context-layer`.
    posthog_feature_flag = "context-layer"
    permission_classes = [IsAuthenticated, APIScopePermission, PostHogFeatureFlagPermission]
    scope_object = "organization"
    scope_object_read_actions = ["status", "tree", "page", "report", "export"]
    scope_object_write_actions = ["enable", "update_page", "commits"]

    # No sandbox-token override here: a run token carries `scoped_teams`, which
    # `APIScopePermission` refuses on this organization-nested route, so it never
    # reaches these actions. Sandbox runs land commits through the project-nested
    # `ContextLayerAgentViewSet` instead; this route serves humans and
    # `organization:write` tokens.

    @extend_schema(
        request=None,
        responses={201: ContextLayerStatusSerializer},
        summary="Enable the context layer",
        description=(
            "Create the organization's wiki with the default structure and import existing channel "
            "CONTEXT.md documents once. Idempotent."
        ),
    )
    @action(methods=["POST"], detail=False)
    def enable(self, request: Request, **kwargs) -> Response:
        user_id = request.user.id if request.user and request.user.is_authenticated else None
        try:
            config = facade.enable_context_layer(self.organization.id, created_by_id=user_id)
        except facade.RestrictedProjectsError as error:
            raise ValidationError(str(error), code="private_projects") from error
        except facade.ContextLayerStoreError as error:
            return _store_error_response(error)
        return Response(
            ContextLayerStatusSerializer({"head_sha": config.head_sha}).data, status=status.HTTP_201_CREATED
        )

    @extend_schema(
        responses={
            200: ContextLayerStatusSerializer,
            404: OpenApiResponse(description="The context layer is not enabled."),
        },
        summary="Get the wiki head",
    )
    @action(methods=["GET"], detail=False)
    def status(self, request: Request, **kwargs) -> Response:
        _assert_no_private_projects(self.organization.id)
        try:
            config = facade.get_config(self.organization.id)
        except facade.ContextLayerStoreError as error:
            return _store_error_response(error)
        return Response(ContextLayerStatusSerializer({"head_sha": config.head_sha}).data)

    @extend_schema(
        responses={200: WikiTreeSerializer, 404: OpenApiResponse(description="The context layer is not enabled.")},
        summary="List wiki pages",
    )
    @action(methods=["GET"], detail=False)
    def tree(self, request: Request, **kwargs) -> Response:
        _assert_no_private_projects(self.organization.id)
        try:
            wiki_tree = facade.get_tree(self.organization.id)
        except facade.ContextLayerStoreError as error:
            return _store_error_response(error)
        return Response(WikiTreeSerializer(wiki_tree).data)

    @extend_schema(
        responses={200: WikiHealthReportSerializer},
        summary="Report wiki health findings",
    )
    @action(methods=["GET"], detail=False, url_path="wiki/report")
    def report(self, request: Request, **kwargs) -> Response:
        _assert_no_private_projects(self.organization.id)
        try:
            report = facade.get_health_report(self.organization.id)
        except facade.ContextLayerStoreError as error:
            return _store_error_response(error)
        return Response(WikiHealthReportSerializer(report).data)

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="path", type=str, required=True, description="Repo-relative Markdown path of the page to read."
            )
        ],
        responses={200: WikiPageSerializer, 404: OpenApiResponse(description="No page at this path.")},
        summary="Read a wiki page",
    )
    @action(methods=["GET"], detail=False, url_path="pages", url_name="pages")
    def page(self, request: Request, **kwargs) -> Response:
        return _read_page(self.organization.id, request)

    @extend_schema(
        request=WikiPageWriteSerializer,
        responses={
            200: ContextLayerStatusSerializer,
            400: LintErrorSerializer,
            409: HeadConflictSerializer,
        },
        summary="Create or replace a wiki page",
    )
    @page.mapping.put
    def update_page(self, request: Request, **kwargs) -> Response:
        return _write_page(self.organization.id, request)

    @extend_schema(
        request=CommitBundleSerializer,
        responses={
            200: ContextLayerStatusSerializer,
            400: LintErrorSerializer,
            409: OpenApiResponse(description="The posted commits conflict with the current head; re-pull and retry."),
        },
        summary="Land agent commits from a git bundle",
    )
    @action(methods=["POST"], detail=False, parser_classes=[MultiPartParser, FormParser])
    def commits(self, request: Request, **kwargs) -> Response:
        return _land_commits(self.organization.id, request)

    @extend_schema(
        responses={200: WikiExportSerializer},
        summary="Export the wiki",
        description="A short-lived download URL for the wiki's current bundle: the whole repo and its history, one file, standard git.",
    )
    @action(methods=["GET"], detail=False)
    def export(self, request: Request, **kwargs) -> Response:
        _assert_no_private_projects(self.organization.id)
        try:
            bundle = facade.get_bundle_export(self.organization.id)
        except facade.ContextLayerStoreError as error:
            return _store_error_response(error)
        return Response(WikiExportSerializer({"url": bundle.url, "head_sha": bundle.head_sha}).data)


@extend_schema(tags=["context_layer"])
class ContextLayerAgentViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """The same organization wiki, reached by an agent run inside a sandbox.

    This exists as a second, project-nested route because a sandbox run token
    carries `scoped_teams`, and `APIScopePermission` accepts those only on a
    project-nested view — on the organization-scoped route above, every sandbox
    token is refused before it reaches any of this. The wiki is still one repo
    per organization; the project in the path is how a run token proves which
    organization it may act for, and is not a scope on the wiki itself.
    """

    posthog_feature_flag = "context-layer"
    permission_classes = [IsAuthenticated, APIScopePermission, PostHogFeatureFlagPermission]
    # The wiki is not an access-control resource, and "organization" is not one a
    # project-nested view can be checked against: `AccessControlPermission` engages
    # here (it no-ops on the organization route, which has no team) and would demand
    # organization *admin* to write — a bar the organization route never sets and
    # the plain members runs act as do not clear. INTERNAL skips that resource
    # lookup while keeping the rest of the chain, including project membership and
    # `scoped_teams` enforcement. It also drops the default scope derivation, so
    # every action below states its scopes explicitly.
    scope_object = "INTERNAL"
    write_actions = ["commits"]

    def dangerously_get_required_scopes(self, request: Request, view=None) -> list[str] | None:  # noqa: ANN001
        """A sandbox run lands commits with task scopes; everyone else uses the organization one.

        `task:write` alone is user-grantable, so it only counts together with
        `internal_run:read` — minted server-side for sandbox runs and rejected by
        every user-facing scope validator, so a person cannot ask for it. Callers
        without that marker need the same `organization:write` the human route asks
        for, which `scope_object = "INTERNAL"` means naming here rather than
        deriving. One consequence of INTERNAL: a `*` (full access) token does not
        short-circuit this check, so it has to carry the organization scope too.
        """
        if self.action not in self.write_actions:
            return None
        access_token = get_oauth_access_token(request)
        token_scopes = set((getattr(access_token, "scope", "") or "").split())
        if INTERNAL_RUN_SCOPE in token_scopes:
            return ["task:write", INTERNAL_RUN_SCOPE]
        return ["organization:write"]

    @extend_schema(
        request=CommitBundleSerializer,
        responses={
            200: ContextLayerStatusSerializer,
            400: LintErrorSerializer,
            409: OpenApiResponse(description="The posted commits conflict with the current head; re-pull and retry."),
        },
        summary="Land agent commits from a git bundle",
    )
    @action(methods=["POST"], detail=False, parser_classes=[MultiPartParser, FormParser])
    def commits(self, request: Request, **kwargs) -> Response:
        return _land_commits(self.organization.id, request)
