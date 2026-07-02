"""Personal Settings → Personal integrations: manage the user's own GitHub integrations.

A ``UserIntegration`` (kind=github) stores the user's own GitHub App installation
plus user-to-server tokens. This gives the user independent repo access at the
personal level, separate from any team-level ``Integration``.

A user may have multiple GitHub integrations (one per GitHub App installation),
allowing coverage of repos across personal accounts and multiple organisations.

Login management is fully handled by ``UserSocialAuth`` (python-social-auth) and
is not controlled here.
"""

import os
from typing import Any, cast
from urllib.parse import urlencode

import requests
import structlog
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import exceptions, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.github_callback import state as github_callback_state
from posthog.api.github_callback.types import (
    APP_CONNECT_FROM_VALUES,
    PERSONAL_INTEGRATIONS_SETTINGS_PATH,
    FlowKind,
    GitHubAuthorizeState,
    github_app_install_url,
    github_oauth_authorize_url,
)
from posthog.api.integration import (
    GitHubBranchesQuerySerializer,
    GitHubBranchesResponseSerializer,
    GitHubReposQuerySerializer,
    GitHubReposRefreshResponseSerializer,
    GitHubReposResponseSerializer,
    validate_github_repository_name,
)
from posthog.auth import OAuthAccessTokenAuthentication, PersonalAPIKeyAuthentication, SessionAuthentication
from posthog.exceptions_capture import capture_exception
from posthog.models.integration import GITHUB_REPOSITORY_REFRESH_COOLDOWN_SECONDS, Integration
from posthog.models.user import User
from posthog.models.user_integration import UserGitHubIntegration, UserIntegration
from posthog.permissions import APIScopePermission
from posthog.rate_limit import UserAuthenticationThrottle
from posthog.user_permissions import UserPermissions

from products.slack_app.backend.feature_flags import is_slack_app_oauth_enabled
from products.slack_app.backend.services.slack_user_oauth import build_invite_url

logger = structlog.get_logger(__name__)


class UserGitHubAccountSerializer(serializers.Serializer):
    type = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="GitHub account type for the installation (e.g. User or Organization).",
    )
    name = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="GitHub login or organization name tied to the installation.",
    )


class UserGitHubIntegrationItemSerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="PostHog UserIntegration row id.")
    kind = serializers.CharField(help_text="Integration kind; always `github` for this API.")
    installation_id = serializers.CharField(help_text="GitHub App installation id.")
    repository_selection = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="Repository selection mode from GitHub (e.g. selected or all).",
    )
    account = UserGitHubAccountSerializer(
        required=False,
        allow_null=True,
        help_text="Installation account metadata from GitHub.",
    )
    uses_shared_installation = serializers.BooleanField(
        help_text="True when this installation id matches a team-level GitHub integration on the active project.",
    )
    created_at = serializers.DateTimeField(help_text="When this integration row was created.")


class UserGitHubIntegrationListResponseSerializer(serializers.Serializer):
    results = UserGitHubIntegrationItemSerializer(
        many=True,
        help_text="GitHub personal integrations for the authenticated user.",
    )


class UserGitHubPrepareCallbackRequestSerializer(serializers.Serializer):
    installation_id = serializers.CharField(help_text="GitHub App installation id being managed on github.com.")


class UserGitHubLinkStartRequestSerializer(serializers.Serializer):
    team_id = serializers.IntegerField(
        required=False,
        allow_null=True,
        help_text="Optional team/project id (e.g. PostHog Code); web UI uses the session's current team.",
    )
    connect_from = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Optional client hint (e.g. posthog_code) for return routing after OAuth.",
    )


class UserGitHubLinkStartResponseSerializer(serializers.Serializer):
    install_url = serializers.CharField(
        help_text="URL to open in the browser to install or authorize the GitHub App for this user.",
    )
    connect_flow = serializers.CharField(
        help_text="OAuth or install flow used for this GitHub connection.",
    )


class UserSlackIntegrationItemSerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="PostHog UserIntegration row id.")
    kind = serializers.CharField(help_text="Integration kind; always `slack` for this API.")
    slack_user_id = serializers.CharField(help_text="Slack user id this PostHog account is linked to.")
    slack_team_id = serializers.CharField(help_text="Slack workspace (team) id the link belongs to.")
    slack_team_name = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="Slack workspace display name as of link time.",
    )
    slack_email_at_link = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="Slack email at the time of linking. Stored for support; not consulted at resolve time.",
    )
    created_at = serializers.DateTimeField(help_text="When this link was first created.")


class UserSlackIntegrationListResponseSerializer(serializers.Serializer):
    results = UserSlackIntegrationItemSerializer(
        many=True,
        help_text="Slack identity links for the authenticated user.",
    )


class UserSlackLinkStartRequestSerializer(serializers.Serializer):
    """Settings-initiated link can target a specific PostHog team + Slack workspace.

    Both are optional — when omitted we fall back to the user's ``current_team``
    and that team's first Slack ``Integration`` (mirrors ``github_start`` for
    the simple case). The frontend passes both explicitly once it has the
    linkable-workspace list and the user has picked a workspace.
    """

    team_id = serializers.IntegerField(
        required=False,
        allow_null=True,
        help_text="Optional team/project id to link against; defaults to the user's current team.",
    )
    slack_team_id = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="Specific Slack workspace id to link against, scoped to the team. Disambiguates when one team has multiple Slack integrations (rare).",
    )


class UserSlackLinkStartResponseSerializer(serializers.Serializer):
    install_url = serializers.CharField(
        help_text="URL to open in the browser to start the Sign-in-with-Slack flow.",
    )


class UserSlackLinkableWorkspaceItemSerializer(serializers.Serializer):
    posthog_team_id = serializers.IntegerField(help_text="PostHog team/project id owning the Slack workspace install.")
    posthog_team_name = serializers.CharField(help_text="PostHog team/project name, for display in a picker.")
    posthog_organization_name = serializers.CharField(
        help_text="PostHog organization name owning the team, for picker disambiguation.",
    )
    slack_team_id = serializers.CharField(help_text="Slack workspace (team) id.")
    slack_team_name = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="Slack workspace display name as known by PostHog.",
    )


class UserSlackLinkableWorkspaceListResponseSerializer(serializers.Serializer):
    results = UserSlackLinkableWorkspaceItemSerializer(
        many=True,
        help_text="Slack workspaces the user could link to but hasn't yet.",
    )


@extend_schema(extensions={"x-product": "core"})
class UserIntegrationViewSet(viewsets.GenericViewSet):
    """`/api/users/@me/integrations/` — manage the user's personal GitHub integrations."""

    scope_object = "user"
    required_scopes: list[str] | None = None
    scope_object_read_actions = [
        "list",
        "retrieve",
        "github_repos",
        "github_branches",
        "slack_linkable",
    ]
    scope_object_write_actions = [
        "create",
        "update",
        "partial_update",
        "patch",
        "destroy",
        "github_start",
        "github_prepare_callback",
        "github_destroy",
        "github_repos_refresh",
        "slack_start",
        "slack_destroy",
    ]

    authentication_classes = [OAuthAccessTokenAuthentication, PersonalAPIKeyAuthentication, SessionAuthentication]
    permission_classes = [IsAuthenticated, APIScopePermission]
    http_method_names = ["get", "post", "delete"]
    serializer_class = UserGitHubIntegrationItemSerializer

    def _get_user(self) -> User:
        """Resolve the target user from the nested ``parent_lookup_uuid`` (same rules as ``UserViewSet``)."""
        request_user = cast(User, self.request.user)
        uuid_param = self.kwargs.get("parent_lookup_uuid")
        if uuid_param is None:
            return request_user
        if uuid_param == "@me":
            return request_user
        if not request_user.is_staff:
            raise exceptions.PermissionDenied(
                "As a non-staff user you're only allowed to access the `@me` user instance."
            )
        user = User.objects.filter(uuid=uuid_param, is_active=True).first()
        if user is None:
            raise exceptions.NotFound()
        return user

    def _team_github_installation_ids(self, user: User) -> set[str]:
        """Installation IDs for the current team's GitHub integrations (for ``uses_shared_installation``)."""
        team = user.current_team
        if team is None:
            return set()

        installation_ids: set[str] = set()
        for ti in Integration.objects.filter(team=team, kind="github").values("integration_id"):
            iid = ti["integration_id"]
            if iid:
                installation_ids.add(str(iid))
        return installation_ids

    @extend_schema(
        summary="List the user's personal integrations of a given kind",
        parameters=[
            OpenApiParameter(
                name="kind",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                enum=["github", "slack"],
                description="Integration kind to list. Defaults to `github` for back-compat with mobile and the Code SDK, which call this endpoint without a query param and expect GitHub-shaped items.",
            ),
        ],
        responses={200: UserGitHubIntegrationListResponseSerializer},
    )
    def list(self, request: Request, **_kwargs) -> Response:
        """Return the authenticated user's personal integrations of a given
        ``kind`` (``github`` or ``slack``).

        The response shape varies per kind because the underlying ``UserIntegration``
        rows carry different identity fields — GitHub rows expose
        ``installation_id`` / ``account`` / ``uses_shared_installation``; Slack
        rows expose ``slack_user_id`` / ``slack_team_id`` / ``slack_team_name``.
        Kind-specific destroy and start actions remain split so their distinct
        semantics (e.g. Slack's lack of "uninstall on last reference") stay
        explicit at the URL layer.

        Default of ``kind=github`` is load-bearing: mobile (``apps/mobile/...``)
        and the Code SDK (``packages/api-client/...``) both call this endpoint
        without a query param today and rely on receiving GitHub rows.
        """
        user = self._get_user()
        kind = request.query_params.get("kind") or "github"
        if kind not in {"github", "slack"}:
            raise exceptions.ValidationError(f"Unsupported integration kind: {kind!r}")

        # Single query and single pass — each row picks its own serializer
        # off `integration.kind`. Today the query is filtered to one kind so
        # the loop only sees that one shape, but the per-row dispatch keeps
        # the door open for dropping the kind default and returning github
        # + slack rows side-by-side in one response.
        integrations = UserIntegration.objects.filter(user=user, kind=kind).order_by("created_at")
        # Only compute the github-specific cross-team installation set when
        # there could be github rows in the response; for `kind=slack` this
        # would be an unused DB roundtrip on every settings page load.
        team_installation_ids: set[str] = self._team_github_installation_ids(user) if kind == "github" else set()
        results: list[dict[str, Any]] = []
        for integration in integrations:
            if integration.kind == "github":
                results.append(
                    _serialize_github_integration(integration, team_integration_installation_ids=team_installation_ids)
                )
            elif integration.kind == "slack":
                results.append(_serialize_slack_integration(integration))
        return Response({"results": results})

    @extend_schema(
        summary="Disconnect a personal GitHub integration",
        responses={204: OpenApiResponse(description="Integration removed.")},
    )
    @action(methods=["DELETE"], detail=False, url_path=r"github/(?P<installation_id>\d+)")
    def github_destroy(self, request: Request, installation_id: str, **_kwargs) -> Response:
        """Remove a specific GitHub installation by its installation_id."""
        user = self._get_user()
        integration = UserIntegration.objects.filter(user=user, kind="github", integration_id=installation_id).first()
        if integration is None:
            raise exceptions.NotFound("No GitHub integration found for this installation.")

        # Notify GitHub to uninstall the App, but only if no other PostHog team or user
        # still relies on this installation (uninstalling breaks it for everyone sharing it).
        try:
            UserGitHubIntegration.uninstall_if_last_reference(
                installation_id, exclude_user_integration_id=integration.id
            )
        except Exception as e:
            capture_exception(e)

        integration.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        summary="List repositories for a personal GitHub installation",
        parameters=[GitHubReposQuerySerializer],
        responses={200: GitHubReposResponseSerializer},
    )
    @action(methods=["GET"], detail=False, url_path=r"github/(?P<installation_id>\d+)/repos")
    def github_repos(self, request: Request, installation_id: str, **_kwargs) -> Response:
        """List repositories accessible to a specific GitHub installation (paginated, cached)."""
        query_serializer = GitHubReposQuerySerializer(data=request.query_params)
        query_serializer.is_valid(raise_exception=True)
        search = query_serializer.validated_data["search"]
        limit = query_serializer.validated_data["limit"]
        offset = query_serializer.validated_data["offset"]

        integration = UserIntegration.objects.filter(
            user=self._get_user(), kind="github", integration_id=installation_id
        ).first()
        if integration is None:
            raise exceptions.NotFound("No GitHub integration found for this installation.")

        github = UserGitHubIntegration(integration)
        repositories, has_more = github.list_cached_repositories(search=search, limit=limit, offset=offset)
        return Response({"repositories": repositories, "has_more": has_more})

    @extend_schema(
        summary="Refresh repositories for a personal GitHub installation",
        request=None,
        responses={200: GitHubReposRefreshResponseSerializer},
    )
    @action(methods=["POST"], detail=False, url_path=r"github/(?P<installation_id>\d+)/repos/refresh")
    def github_repos_refresh(self, request: Request, installation_id: str, **_kwargs) -> Response:
        """Refresh repositories accessible to a specific GitHub installation."""
        integration = UserIntegration.objects.filter(
            user=self._get_user(), kind="github", integration_id=installation_id
        ).first()
        if integration is None:
            raise exceptions.NotFound("No GitHub integration found for this installation.")

        github = UserGitHubIntegration(integration)
        repositories = github.sync_repository_cache(
            min_refresh_interval_seconds=GITHUB_REPOSITORY_REFRESH_COOLDOWN_SECONDS
        )
        return Response({"repositories": repositories})

    @extend_schema(
        summary="List branches for a personal GitHub installation repository",
        parameters=[GitHubBranchesQuerySerializer],
        responses={200: GitHubBranchesResponseSerializer},
    )
    @action(methods=["GET"], detail=False, url_path=r"github/(?P<installation_id>\d+)/branches")
    def github_branches(self, request: Request, installation_id: str, **_kwargs) -> Response:
        """List branches for a repository accessible to a personal GitHub installation."""
        params = GitHubBranchesQuerySerializer(data=request.query_params)
        params.is_valid(raise_exception=True)

        repo: str = params.validated_data["repo"]
        search: str = params.validated_data["search"]
        limit: int = params.validated_data["limit"]
        offset: int = params.validated_data["offset"]

        validate_github_repository_name(repo)

        integration = UserIntegration.objects.filter(
            user=self._get_user(), kind="github", integration_id=installation_id
        ).first()
        if integration is None:
            raise exceptions.NotFound("No GitHub integration found for this installation.")

        github = UserGitHubIntegration(integration)
        branches, default_branch, has_more = github.list_cached_branches(
            repo,
            search=search,
            limit=limit,
            offset=offset,
        )

        return Response({"branches": branches, "default_branch": default_branch, "has_more": has_more})

    @extend_schema(
        summary="Start GitHub personal integration linking",
        request=UserGitHubLinkStartRequestSerializer,
        responses={200: UserGitHubLinkStartResponseSerializer},
    )
    @action(
        methods=["POST"],
        detail=False,
        url_path="github/start",
        throttle_classes=[UserAuthenticationThrottle],
    )
    def github_start(self, request: Request, **_kwargs) -> Response:
        """Start GitHub linking: either full App install or OAuth-only (user-to-server).

        ``**_kwargs`` absorbs ``parent_lookup_uuid`` from the nested
        ``/api/users/{uuid}/integrations/`` router (same pattern as ``local_evaluation``
        under projects).

        Usually returns ``install_url`` pointing at ``/installations/new`` so the
        user can pick any GitHub org (new or already connected).  GitHub's install
        page handles both cases: orgs where the app is installed show "Configure"
        (no admin needed), orgs where it isn't show "Install" (needs admin).

        **OAuth fast path:** when the current project already has a team-level
        GitHub installation, and the user has no ``UserIntegration`` for that
        installation yet, we skip the org picker and redirect straight to
        ``/login/oauth/authorize`` so the user only authorizes themselves.
        ``connect_from`` is preserved for first-party clients so they return to
        the originating client immediately.

        In both cases the response key is ``install_url`` for compatibility with callers.
        """
        from django.utils.crypto import get_random_string

        token = get_random_string(48)
        state = urlencode({"token": token, "source": "user_integration"})
        user = self._get_user()
        team = _resolve_team_for_github_start(user, self.request)
        connect_from = request.data.get("connect_from")

        if fast_path_response := _attempt_app_oauth_fast_path(user, team, token, state, connect_from):
            return fast_path_response

        if connect_from in APP_CONNECT_FROM_VALUES:
            if _team_github_installation_id(team) is None:
                github_callback_state.store_unified_authorize_state(
                    GitHubAuthorizeState(
                        token=token,
                        flow=FlowKind.OAUTH_DISCOVER,
                        user_id=user.id,
                        connect_from=connect_from,
                    ),
                )
                return Response({"install_url": github_oauth_authorize_url(state), "connect_flow": "oauth_discover"})

        # If the user already has linked integrations, check whether there are
        # any GitHub App installations they haven't linked yet. If everything
        # accessible is already linked, there's nothing to add.
        has_unlinked = _has_unlinked_github_installations(user)
        if has_unlinked is False:
            raise exceptions.ValidationError(
                "All GitHub App installations accessible to your account are already linked."
            )

        github_callback_state.store_unified_authorize_state(
            GitHubAuthorizeState(
                token=token,
                flow=FlowKind.PERSONAL_INSTALL,
                user_id=user.id,
                connect_from=str(connect_from) if connect_from else None,
            ),
        )
        return Response(
            {
                "install_url": github_app_install_url(state),
                "connect_flow": "app_install",
            }
        )

    @extend_schema(
        request=UserGitHubPrepareCallbackRequestSerializer, responses={204: OpenApiResponse(description="No content")}
    )
    @action(methods=["POST"], detail=False, url_path="github/prepare_callback")
    def github_prepare_callback(self, request: Request, **_kwargs) -> Response:
        """Seed personal GitHub manage callback state before opening installation settings on GitHub."""
        serializer = UserGitHubPrepareCallbackRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        installation_id = str(serializer.validated_data["installation_id"])
        user = self._get_user()
        token = os.urandom(33).hex()
        github_callback_state.store_unified_authorize_state(
            GitHubAuthorizeState(
                token=token,
                flow=FlowKind.PERSONAL_UPDATE,
                user_id=user.id,
                installation_id=installation_id,
                next_url=PERSONAL_INTEGRATIONS_SETTINGS_PATH,
            ),
        )
        return Response(status=204)

    @extend_schema(
        summary="List Slack workspaces this user could link to",
        responses={200: UserSlackLinkableWorkspaceListResponseSerializer},
    )
    @action(methods=["GET"], detail=False, url_path="slack/linkable_workspaces")
    def slack_linkable(self, request: Request, **_kwargs) -> Response:
        """Return Slack workspaces in the user's organizations that they have
        not yet linked. The settings UI uses this list to decide whether to
        show a "Link my Slack account" button (non-empty list) and what to
        offer in the picker when several are connectable.
        """
        user = self._get_user()
        org_ids = set(user.organization_memberships.values_list("organization_id", flat=True))
        if not org_ids:
            return Response({"results": []})

        already_linked_slack_team_ids = set(
            UserIntegration.objects.filter(
                user=user,
                kind=UserIntegration.IntegrationKind.SLACK,
            ).values_list("config__slack_team_id", flat=True)
        )

        candidates = (
            Integration.objects.filter(kind="slack", team__organization_id__in=org_ids)
            .exclude(integration_id__in=already_linked_slack_team_ids)
            .select_related("team", "team__organization")
        )

        # Skip projects the user can't actually access (private project, no role
        # via access-control, etc.). Without the per-team check, an org member
        # would see Slack workspace IDs + project names for every project in
        # their orgs — including private ones their `effective_membership_level`
        # is `None` for. Using per-team `effective_membership_level` rather than
        # `user.teams` mirrors `resolve_user_for_workspace` and dodges the
        # `Organization.first()`-feature-flags quirk that gates `user.teams`.
        permissions = UserPermissions(user=user)

        results: list[dict[str, Any]] = []
        for integration in candidates:
            if permissions.team(integration.team).effective_membership_level is None:
                continue
            # Feature-flag check per workspace so an org that hasn't rolled out
            # the flag yet doesn't show up in another org's picker.
            if not is_slack_app_oauth_enabled(integration, integration.integration_id):
                continue
            # `(config or {}).get("team", {})` doesn't defend against an explicit
            # ``config["team"] = None`` — dict.get returns the literal None
            # rather than the default — so we coerce defensively before the
            # second `.get("name")`.
            team_block = (integration.config or {}).get("team") or {}
            results.append(
                {
                    "posthog_team_id": integration.team_id,
                    "posthog_team_name": integration.team.name,
                    "posthog_organization_name": integration.team.organization.name,
                    "slack_team_id": integration.integration_id,
                    "slack_team_name": team_block.get("name"),
                }
            )
        return Response({"results": results})

    @extend_schema(
        summary="Start Slack identity link from settings",
        request=UserSlackLinkStartRequestSerializer,
        responses={200: UserSlackLinkStartResponseSerializer},
    )
    @action(methods=["POST"], detail=False, url_path="slack/start", throttle_classes=[UserAuthenticationThrottle])
    def slack_start(self, request: Request, **_kwargs) -> Response:
        """Mint a Sign-in-with-Slack invite URL initiated from settings, without
        Slack-DM context. The returned URL takes the user through PostHog login
        (already satisfied here), then to Slack OAuth, then back to our callback
        which writes the ``UserIntegration`` row.

        Without body params, falls back to the user's ``current_team`` and that
        team's first Slack ``Integration`` — works when there's exactly one
        linkable workspace. With ``team_id`` + ``slack_team_id``, links against
        the exact pair (what the frontend uses when a picker is shown).

        Refuses if the target team has no matching Slack workspace, if the
        feature flag is off for the workspace, or if the user is already linked
        to it.
        """
        user = self._get_user()
        team = _resolve_team_for_github_start(user, request)
        if team is None:
            raise exceptions.ValidationError("No team available for this user.")

        # If the caller specifies a Slack workspace explicitly, honor it (this
        # is the picker path). Otherwise pick the first Slack integration on
        # the resolved team (the simple "Link my Slack account" path).
        body: Any = request.data if isinstance(request.data, dict) else {}
        slack_team_id_hint = body.get("slack_team_id")
        workspace_query = Integration.objects.filter(team=team, kind="slack")
        if slack_team_id_hint:
            workspace_query = workspace_query.filter(integration_id=slack_team_id_hint)
        workspace = workspace_query.first()
        if workspace is None:
            raise exceptions.ValidationError(
                "This project has no Slack workspace connected. Ask an admin to install the Slack app first."
            )

        if not is_slack_app_oauth_enabled(workspace, workspace.integration_id):
            raise exceptions.PermissionDenied("Slack identity linking is not enabled for this organization.")

        if UserIntegration.objects.filter(
            user=user,
            kind=UserIntegration.IntegrationKind.SLACK,
            config__slack_team_id=workspace.integration_id,
        ).exists():
            raise exceptions.ValidationError("You're already linked to this Slack workspace.")

        install_url = build_invite_url(
            slack_user_id=None,
            slack_team_id=workspace.integration_id,
            posthog_team_id=team.id,
            channel=None,
            thread_ts=None,
        )
        return Response({"install_url": install_url})

    @extend_schema(
        summary="Unlink a Slack identity",
        responses={204: OpenApiResponse(description="Slack link removed.")},
    )
    # Restrict the slack_user_id capture to Slack's real id format ("U..." for
    # human users, "W..." for Enterprise Grid). A looser regex would shadow
    # sibling actions like ``slack/start`` and return 405 on their POSTs.
    @action(methods=["DELETE"], detail=False, url_path=r"slack/(?P<slack_user_id>[UW][A-Z0-9]+)")
    def slack_destroy(self, request: Request, slack_user_id: str, **_kwargs) -> Response:
        """Remove a Slack identity link by Slack user id. Idempotent and
        flag-agnostic — users must always be able to unlink even after the
        feature flag is turned off."""
        user = self._get_user()
        integration = UserIntegration.objects.filter(
            user=user,
            kind=UserIntegration.IntegrationKind.SLACK,
            integration_id=slack_user_id,
        ).first()
        if integration is None:
            raise exceptions.NotFound("No Slack link found for this Slack user id.")
        integration.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


def _resolve_team_for_github_start(user: User, request: Request):
    """Resolve which team to use for team-level GitHub install discovery.

    PostHog Code passes ``team_id`` (project/team) in the JSON body because the
    session's ``user.current_team`` may not match the app UI. The web app omits
    it and uses ``current_team``.
    """
    data: Any = request.data
    if not isinstance(data, dict):
        data = {}
    raw_id = data.get("team_id")
    if raw_id is not None and raw_id != "":
        try:
            tid = int(raw_id)
        except (TypeError, ValueError):
            raise exceptions.ValidationError("team_id must be an integer")
        team = user.teams.filter(id=tid).first()
        if team is None:
            raise exceptions.ValidationError("Invalid or inaccessible team_id for this user.")
        return team
    return user.current_team


def _has_unlinked_github_installations(user: User) -> bool | None:
    """Check whether the user has GitHub App installations they haven't linked yet.

    Uses the user's existing OAuth token to call ``GET /user/installations``
    and compares against their ``UserIntegration`` rows.

    Returns ``True`` if unlinked installations exist, ``False`` if all are
    linked, or ``None`` if the check couldn't be performed (no existing
    integration, token refresh failed, network error).
    """
    any_integration = UserIntegration.objects.filter(user=user, kind="github").exclude(sensitive_config={}).first()
    if any_integration is None:
        return None

    github = UserGitHubIntegration(any_integration)
    try:
        token = github.get_usable_user_access_token()
    except Exception:
        return None

    try:
        response = requests.get(
            "https://api.github.com/user/installations",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            params={"per_page": 100},
            timeout=10,
        )
    except requests.RequestException:
        return None

    if response.status_code != 200:
        return None

    try:
        installations = response.json().get("installations", [])
    except Exception:
        return None

    github_installation_ids = {str(inst["id"]) for inst in installations if isinstance(inst, dict) and "id" in inst}
    linked_ids = set(UserIntegration.objects.filter(user=user, kind="github").values_list("integration_id", flat=True))
    return bool(github_installation_ids - linked_ids)


def _team_github_installation_id(team: Any) -> str | None:
    if team is None:
        return None
    team_row = (
        Integration.objects.filter(team=team, kind="github")
        .exclude(integration_id__isnull=True)
        .exclude(integration_id="")
        .order_by("id")
        .first()
    )
    return str(team_row.integration_id) if team_row is not None and team_row.integration_id else None


def _attempt_app_oauth_fast_path(
    user: User, team: Any, token: str, state: str, connect_from: str | None
) -> Response | None:
    """If the team has a GitHub installation the user hasn't linked yet, return
    an OAuth-only ``/login/oauth/authorize`` redirect so users authorize against
    the already-installed App — no org picker needed. ``connect_from`` is
    preserved so first-party app callbacks return to the right client.

    Returns ``None`` when the fast path doesn't apply (no team integration,
    user already linked, or missing config).
    """
    team_installation_id = _team_github_installation_id(team)
    if team_installation_id is None:
        return None
    if UserIntegration.objects.filter(user=user, kind="github", integration_id=team_installation_id).exists():
        return None
    github_callback_state.store_unified_authorize_state(
        GitHubAuthorizeState(
            token=token,
            flow=FlowKind.PERSONAL_OAUTH,
            user_id=user.id,
            installation_id=team_installation_id,
            connect_from=connect_from,
        ),
    )
    return Response({"install_url": github_oauth_authorize_url(state), "connect_flow": "oauth_authorize"})


def _serialize_github_integration(
    integration: UserIntegration,
    *,
    team_integration_installation_ids: set[str],
) -> dict[str, Any]:
    """Build the response payload for a single GitHub UserIntegration."""
    return {
        "id": integration.id,
        "kind": "github",
        "installation_id": integration.integration_id,
        "repository_selection": integration.config.get("repository_selection"),
        "account": integration.config.get("account"),
        "uses_shared_installation": integration.integration_id in team_integration_installation_ids,
        "created_at": integration.created_at,
    }


def _serialize_slack_integration(integration: UserIntegration) -> dict[str, Any]:
    """Build the response payload for a single Slack UserIntegration row."""
    config = integration.config or {}
    return {
        "id": integration.id,
        "kind": "slack",
        "slack_user_id": integration.integration_id,
        "slack_team_id": config.get("slack_team_id"),
        "slack_team_name": config.get("slack_team_name"),
        "slack_email_at_link": config.get("slack_email_at_link"),
        "created_at": integration.created_at,
    }
