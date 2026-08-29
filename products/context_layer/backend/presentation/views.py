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
from posthog.redis import get_client
from posthog.temporal.oauth import LOOP_CONTEXT_INTERNAL_SCOPE

from products.context_layer.backend.facade import api as facade
from products.context_layer.backend.presentation.serializers import (
    ChannelWikiPageSerializer,
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
from products.tasks.backend.facade import api as tasks_facade

# Ordinary task runs can land wiki commits with nothing but the writer lock
# pacing them, so a runaway sandbox agent gets a hard daily ceiling per run.
RUN_COMMITS_PER_DAY_CAP = 20


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
    if isinstance(error, facade.DependencyUnavailableError):
        return Response(
            {"detail": "The context layer is temporarily unavailable. Try again later."},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    raise error


def _read_page(organization_id, request: Request) -> Response:  # noqa: ANN001
    try:
        wiki_page = facade.get_page(organization_id, request.query_params.get("path", ""))
    except facade.ContextLayerStoreError as error:
        return _store_error_response(error)
    return Response(WikiPageSerializer(wiki_page).data)


def _assert_loop_write_in_scope(organization_id, request: Request, path: str, content: str) -> None:  # noqa: ANN001
    """A loop run may only write the context page it was configured to maintain.

    Reads stay open, because the wiki is organization-wide reference material
    every agent is meant to draw on. Writes cannot be: the agent route's scope
    override accepts a `task:write` token, so without this a loop steered by
    injected text could rewrite AGENTS.md, and with it the instructions every
    agent in the organization starts from. Mirrors the target check the legacy
    channel-instructions endpoint already makes.

    A no-op for any caller without the loop provenance scope, so it is safe to
    run on every write and both routes stay bound by it.
    """
    access_token = get_oauth_access_token(request)
    token_scopes = set((getattr(access_token, "scope", "") or "").split())
    if LOOP_CONTEXT_INTERNAL_SCOPE not in token_scopes:
        return

    denied = PermissionDenied("This loop can update only the context page configured for this run.")
    sandbox_task_id = getattr(access_token, "sandbox_task_id", None)
    if sandbox_task_id is None:
        raise denied

    # Both sides resolve inside this organization's own wiki index, so a run
    # cannot reach another organization's pages even by naming its channel.
    configured_channel_id = tasks_facade.loop_context_channel_id_for_task(sandbox_task_id)
    if configured_channel_id is None:
        raise denied
    requested_channel_id = facade.resolve_page_channel(organization_id, path)
    if configured_channel_id == requested_channel_id:
        return
    if requested_channel_id is not None:
        raise denied
    try:
        _assert_loop_may_create_channel_page(organization_id, configured_channel_id, path, content, denied)
    except facade.ContextLayerStoreError as error:
        # A vanished channel or wiki mid-write reads as out of scope, not a 500.
        raise denied from error


def _assert_loop_may_create_channel_page(
    organization_id,  # noqa: ANN001
    channel_id: str,
    path: str,
    content: str,
    denied: PermissionDenied,
) -> None:
    """A loop may create its channel's page when the channel truly has none.

    Channels created after wiki enablement never went through the one-time
    import, so their loops would otherwise fall back to legacy channel
    instructions forever. Everything is pinned: the channel must have no page,
    the path must be exactly the one resolution proposed, nothing may already
    exist there, and the content's frontmatter must claim the configured
    channel — so the loop cannot plant a page that resolution would hand to a
    different channel.
    """
    if facade.resolve_channel_page(organization_id, channel_id) is not None:
        raise denied
    if path in facade.get_tree(organization_id).paths:
        raise denied
    if path != facade.proposed_channel_page_path(organization_id, channel_id):
        raise denied
    if facade.page_frontmatter_channel_id(content) != channel_id:
        raise denied


def _read_channel_page(organization_id, channel_id: str, *, propose_on_miss: bool = False) -> Response:  # noqa: ANN001
    try:
        path = facade.resolve_channel_page(organization_id, channel_id)
        if path is None and propose_on_miss:
            # The channel has no page yet (created after enablement); hand the
            # caller the canonical path to create it at instead of a dead end.
            proposed = facade.proposed_channel_page_path(organization_id, channel_id)
            return Response(ChannelWikiPageSerializer({"path": proposed, "exists": False}).data)
    except facade.ContextLayerStoreError as error:
        return _store_error_response(error)
    if path is None:
        raise NotFound("This channel has no page in the context wiki.")
    return Response(ChannelWikiPageSerializer({"path": path}).data)


def _write_page(organization_id, request: Request) -> Response:  # noqa: ANN001
    serializer = WikiPageWriteSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    _assert_loop_write_in_scope(
        organization_id, request, serializer.validated_data["path"], serializer.validated_data["content"]
    )
    _assert_run_commit_cap(request)
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


def _assert_run_commit_cap(request: Request) -> None:
    """Cap how many landings (bundles or page writes) one sandbox run gets per day.

    Loops have their own daily fire caps, but an ordinary task run landing
    wiki changes has nothing but the writer lock pacing it. Keyed on the run
    provenance the token carries; human and PAT callers have none and stay
    uncapped.
    """
    access_token = get_oauth_access_token(request)
    sandbox_task_id = getattr(access_token, "sandbox_task_id", None)
    if sandbox_task_id is None:
        return
    redis_client = get_client()
    key = f"context_layer:run_commit_cap:{sandbox_task_id}"
    landed = redis_client.incr(key)
    redis_client.expire(key, 86400)
    if landed > RUN_COMMITS_PER_DAY_CAP:
        raise Throttled(detail="This run has landed too many wiki commits today.")


def _land_commits(organization_id, request: Request) -> Response:  # noqa: ANN001
    access_token = get_oauth_access_token(request)
    token_scopes = set((getattr(access_token, "scope", "") or "").split())
    if LOOP_CONTEXT_INTERNAL_SCOPE in token_scopes:
        # Bundles bypass the page binding _assert_loop_write_in_scope enforces,
        # so a loop run must land its edits through the page endpoint instead.
        raise PermissionDenied("This loop can update only its context page, not land commit bundles.")
    serializer = CommitBundleSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    _assert_run_commit_cap(request)
    bundle_bytes = serializer.validated_data["bundle"].read()
    branch = serializer.validated_data.get("branch")
    try:
        if branch:
            head_sha = facade.land_dream_branch(
                organization_id,
                bundle_bytes,
                branch=branch,
                summary=serializer.validated_data.get("summary") or None,
            )
        else:
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
    scope_object_read_actions = ["status", "tree", "page", "report", "channel_page", "export"]
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
        responses={
            200: ChannelWikiPageSerializer,
            404: OpenApiResponse(description="This channel has no page in the context wiki."),
        },
        summary="Resolve a channel's wiki page",
    )
    @action(methods=["GET"], detail=False, url_path=r"channel-pages/(?P<channel_id>[^/.]+)")
    def channel_page(self, request: Request, channel_id: str, **kwargs) -> Response:
        return _read_channel_page(self.organization.id, channel_id)

    @extend_schema(
        request=WikiPageWriteSerializer,
        responses={
            200: ContextLayerStatusSerializer,
            400: LintErrorSerializer,
            403: OpenApiResponse(
                description="The wiki is unavailable, or a loop run targeted a page outside its own context."
            ),
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
    read_actions = ["page", "channel_page"]
    write_actions = ["update_page", "commits"]

    # Which task scope each action accepts, and the provenance marker that has to
    # come with it. A sandbox run lands commits; a context-maintaining loop run
    # reads and rewrites its own page.
    _RUN_SCOPES = {
        "commits": ("task:write", INTERNAL_RUN_SCOPE),
        "page": ("task:read", LOOP_CONTEXT_INTERNAL_SCOPE),
        "channel_page": ("task:read", LOOP_CONTEXT_INTERNAL_SCOPE),
        "update_page": ("task:write", LOOP_CONTEXT_INTERNAL_SCOPE),
    }

    def dangerously_get_required_scopes(self, request: Request, view=None) -> list[str] | None:  # noqa: ANN001
        """A run acts with task scopes; everyone else faces the organization ones.

        A task scope alone is user-grantable, so it only counts together with the
        action's provenance marker — minted server-side for runs and rejected by
        every user-facing scope validator, so a person cannot ask for it. Callers
        without that marker need the same organization scope the human route asks
        for, which `scope_object = "INTERNAL"` means naming here rather than
        deriving. One consequence of INTERNAL: a `*` (full access) token does not
        short-circuit this check, so it has to carry the organization scope too.
        """
        required = self._RUN_SCOPES.get(self.action)
        if required is not None:
            task_scope, provenance_scope = required
            access_token = get_oauth_access_token(request)
            token_scopes = set((getattr(access_token, "scope", "") or "").split())
            if provenance_scope in token_scopes:
                return [task_scope, provenance_scope]
        if self.action in self.write_actions:
            return ["organization:write"]
        if self.action in self.read_actions:
            return ["organization:read"]
        return None

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
        responses={
            200: ChannelWikiPageSerializer,
            404: OpenApiResponse(description="This channel does not exist, or the wiki is not enabled."),
        },
        summary="Resolve a channel's wiki page",
        description=(
            "The channel's page path. When the channel has no page yet, responds with the canonical "
            "path to create it at and `exists: false`."
        ),
    )
    @action(methods=["GET"], detail=False, url_path=r"channel-pages/(?P<channel_id>[^/.]+)")
    def channel_page(self, request: Request, channel_id: str, **kwargs) -> Response:
        # Unlike the organization route, a miss proposes a create path: a loop
        # maintaining a post-enablement channel needs somewhere to publish.
        return _read_channel_page(self.organization.id, channel_id, propose_on_miss=True)

    @extend_schema(
        request=WikiPageWriteSerializer,
        responses={
            200: ContextLayerStatusSerializer,
            400: LintErrorSerializer,
            403: OpenApiResponse(
                description="The wiki is unavailable, or a loop run targeted a page outside its own context."
            ),
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
