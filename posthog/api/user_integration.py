"""Personal Settings → Personal integrations: manage the user's own GitHub integrations.

A ``UserIntegration`` (kind=github) stores the user's own GitHub App installation
plus user-to-server tokens. This gives the user independent repo access at the
personal level, separate from any team-level ``Integration``.

A user may have multiple GitHub integrations (one per GitHub App installation),
allowing coverage of repos across personal accounts and multiple organisations.

Login management is fully handled by ``UserSocialAuth`` (python-social-auth) and
is not controlled here.
"""

import re
from typing import Any, cast
from urllib.parse import parse_qs, urlencode

from django.conf import settings
from django.core.cache import cache
from django.http import HttpRequest, HttpResponseRedirect
from django.shortcuts import redirect
from django.views.decorators.http import require_http_methods

import requests
import structlog
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import exceptions, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.integration import (
    GITHUB_INSTALL_STATE_CACHE_PREFIX,
    GITHUB_INSTALL_STATE_TTL_SECONDS,
    GitHubBranchesQuerySerializer,
    GitHubBranchesResponseSerializer,
    GitHubReposQuerySerializer,
    GitHubReposRefreshResponseSerializer,
    GitHubReposResponseSerializer,
    github_oauth_redirect_uri,
    validate_github_repository_name,
)
from posthog.auth import (
    OAuthAccessTokenAuthentication,
    PersonalAPIKeyAuthentication,
    SessionAuthentication,
    session_auth_required,
)
from posthog.models.instance_setting import get_instance_settings
from posthog.models.integration import (
    GITHUB_REPOSITORY_REFRESH_COOLDOWN_SECONDS,
    GitHubInstallationAccess,
    GitHubIntegration,
    Integration,
)
from posthog.models.user import User
from posthog.models.user_integration import (
    UserGitHubIntegration,
    UserIntegration,
    user_github_integration_from_installation,
)
from posthog.permissions import APIScopePermission
from posthog.rate_limit import UserAuthenticationThrottle

logger = structlog.get_logger(__name__)

PERSONAL_INTEGRATIONS_SETTINGS_PATH = "/settings/user-personal-integrations"
ACCOUNT_CONNECTED_GITHUB_INTEGRATION_PATH = "/account-connected/github-integration"


def _github_oauth_authorize_url(state: str) -> str:
    """Build the GitHub App user authorization URL."""
    if not settings.GITHUB_APP_CLIENT_ID:
        raise exceptions.ValidationError("GitHub App client ID is not configured (GITHUB_APP_CLIENT_ID missing).")
    return "https://github.com/login/oauth/authorize?" + urlencode(
        {"client_id": settings.GITHUB_APP_CLIENT_ID, "redirect_uri": github_oauth_redirect_uri(), "state": state}
    )


def _github_app_install_url(state: str) -> str:
    """Build the GitHub App install URL."""
    instance_settings = get_instance_settings(["GITHUB_APP_SLUG"])
    app_slug = instance_settings.get("GITHUB_APP_SLUG")
    if not app_slug:
        raise exceptions.ValidationError("GitHub App is not configured on this instance (missing GITHUB_APP_SLUG).")
    return f"https://github.com/apps/{app_slug}/installations/new?{urlencode({'state': state})}"


def _github_state_token(state_raw: str) -> str:
    state_params = parse_qs(state_raw)
    return state_params["token"][0] if "token" in state_params else state_raw


def _github_user_installation_ids(user_access_token: str) -> list[str]:
    """List GitHub App installations visible to a user-to-server token."""
    response = requests.get(
        "https://api.github.com/user/installations",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {user_access_token}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        params={"per_page": 100},
        timeout=10,
    )
    if response.status_code != 200:
        logger.warning("github_link: failed to list user installations", status_code=response.status_code)
        raise requests.RequestException(f"Unexpected status {response.status_code} listing user installations")

    installations = response.json().get("installations", [])
    ids: list[str] = []
    if isinstance(installations, list):
        for installation in installations:
            if isinstance(installation, dict) and installation.get("id") is not None:
                ids.append(str(installation["id"]))
    return ids


def _redirect_to_github_app_install(user: User, connect_from: str | None) -> HttpResponseRedirect:
    """Continue from user OAuth discovery to app installation when no installation exists yet."""
    from django.utils.crypto import get_random_string

    token = get_random_string(48)
    state = urlencode({"token": token, "source": "user_integration"})
    install_state_payload: dict[str, Any] = {"user_id": user.id}
    if connect_from:
        install_state_payload["connect_from"] = connect_from
    cache.set(
        f"{GITHUB_INSTALL_STATE_CACHE_PREFIX}{token}",
        install_state_payload,
        timeout=GITHUB_INSTALL_STATE_TTL_SECONDS,
    )
    return redirect(_github_app_install_url(state))


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


@extend_schema(tags=["core"])
class UserIntegrationViewSet(viewsets.GenericViewSet):
    """`/api/users/@me/integrations/` — manage the user's personal GitHub integrations."""

    scope_object = "user"
    required_scopes: list[str] | None = None
    scope_object_read_actions = ["list", "retrieve", "github_repos", "github_branches"]
    scope_object_write_actions = [
        "create",
        "update",
        "partial_update",
        "patch",
        "destroy",
        "github_start",
        "github_destroy",
        "github_repos_refresh",
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
        summary="List personal GitHub integrations",
        responses={200: UserGitHubIntegrationListResponseSerializer},
    )
    def list(self, request: Request, **_kwargs) -> Response:
        user = self._get_user()
        integrations = UserIntegration.objects.filter(user=user, kind="github").order_by("created_at")
        team_installation_ids = self._team_github_installation_ids(user)
        return Response(
            {
                "results": [
                    _serialize_github_integration(integration, team_integration_installation_ids=team_installation_ids)
                    for integration in integrations
                ],
            }
        )

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

        **PostHog Code fast path:** when ``connect_from`` is ``"posthog_code"``,
        the current project already has a team-level GitHub installation, and the
        user has no ``UserIntegration`` for that installation yet, we skip the org
        picker and redirect straight to ``/login/oauth/authorize`` so the user
        only authorizes themselves and returns to PostHog Code immediately.

        In both cases the response key is ``install_url`` for compatibility with callers.
        """
        from django.utils.crypto import get_random_string

        token = get_random_string(48)
        state = urlencode({"token": token, "source": "user_integration"})
        user = self._get_user()
        team = _resolve_team_for_github_start(user, self.request)
        connect_from = request.data.get("connect_from")

        if connect_from == "posthog_code":
            if fast_path_response := _attempt_posthog_code_oauth_fast_path(user, team, token, state):
                return fast_path_response
            if _team_github_installation_id(team) is None:
                cache.set(
                    f"{GITHUB_INSTALL_STATE_CACHE_PREFIX}{token}",
                    {"user_id": user.id, "connect_from": connect_from, "flow": "oauth_discover"},
                    timeout=GITHUB_INSTALL_STATE_TTL_SECONDS,
                )
                return Response({"install_url": _github_oauth_authorize_url(state), "connect_flow": "oauth_discover"})

        # If the user already has linked integrations, check whether there are
        # any GitHub App installations they haven't linked yet. If everything
        # accessible is already linked, there's nothing to add.
        has_unlinked = _has_unlinked_github_installations(user)
        if has_unlinked is False:
            raise exceptions.ValidationError(
                "All GitHub App installations accessible to your account are already linked."
            )

        install_state_payload: dict[str, Any] = {"user_id": user.id}
        if connect_from:
            install_state_payload["connect_from"] = connect_from
        cache.set(
            f"{GITHUB_INSTALL_STATE_CACHE_PREFIX}{token}",
            install_state_payload,
            timeout=GITHUB_INSTALL_STATE_TTL_SECONDS,
        )
        return Response(
            {
                "install_url": _github_app_install_url(state),
                "connect_flow": "app_install",
            }
        )


def _posthog_code_flow_from_state_query(request: HttpRequest) -> bool:
    """Best-effort: OAuth error callbacks may still include ``state``; read cache (do not delete)."""
    state_raw = request.GET.get("state")
    if not state_raw:
        return False
    token = _github_state_token(state_raw)
    cache_key = f"{GITHUB_INSTALL_STATE_CACHE_PREFIX}{token}"
    state_payload = cache.get(cache_key)
    return bool(
        state_payload
        and state_payload.get("user_id") == request.user.id
        and state_payload.get("connect_from") == "posthog_code"
    )


@require_http_methods(["GET"])
@session_auth_required
def github_link_complete(request: HttpRequest) -> HttpResponseRedirect:
    """GitHub App installation + user authorization callback.

    **Install flow** (``/installations/new``): GitHub sends ``installation_id``,
    ``code``, and ``state`` in the query string.

    **OAuth-only flow** (``/login/oauth/authorize`` when the team already has the
    app installed): GitHub sends only ``code`` and ``state``; ``installation_id``
    is read from validated server-side state.

    Steps: validate state, resolve ``installation_id``, exchange ``code`` for
    user-to-server tokens, fetch installation token, create/update ``UserIntegration``.
    """

    posthog_code_flow = False

    def _error(reason: str) -> HttpResponseRedirect:
        logger.warning("github_link: redirecting with error", reason=reason, user_id=request.user.id)
        if posthog_code_flow:
            q = urlencode({"provider": "github", "error": reason})
            return redirect(f"{ACCOUNT_CONNECTED_GITHUB_INTEGRATION_PATH}?{q}")
        return redirect(f"{PERSONAL_INTEGRATIONS_SETTINGS_PATH}?github_link_error={reason}")

    # GitHub appends ?error=... when the user denied consent.
    if github_error := request.GET.get("error"):
        logger.warning(
            "github_link: GitHub returned error on callback",
            error=github_error,
            description=request.GET.get("error_description"),
            user_id=request.user.id,
        )
        if _posthog_code_flow_from_state_query(request):
            posthog_code_flow = True
        return _error(github_error if github_error == "access_denied" else "github_oauth_error")

    code = request.GET.get("code")
    state_raw = request.GET.get("state")

    if not code or not state_raw:
        return _error("missing_params")

    # The frontend extracts the raw token from the URL-encoded state before forwarding
    # here, so state_raw is normally the 48-char random token.  Handle both forms so
    # direct backend calls (e.g. in tests) and any future flow changes work correctly.
    token = _github_state_token(state_raw)

    # Validate state
    cache_key = f"{GITHUB_INSTALL_STATE_CACHE_PREFIX}{token}"
    state_payload = cache.get(cache_key)
    if not state_payload or state_payload.get("user_id") != request.user.id:
        return _error("invalid_state")
    if state_payload.get("connect_from") == "posthog_code":
        posthog_code_flow = True
    cache.delete(cache_key)

    flow = state_payload.get("flow")
    oauth_flow = flow == "oauth_authorize"
    oauth_discover_flow = flow == "oauth_discover"
    team_oauth_flow = flow == "team_oauth_authorize"
    team_oauth_team_id: int | None = None
    team_oauth_next: str | None = None
    installation_ids: list[str] = []
    if oauth_flow:
        installation_id = state_payload.get("installation_id")
        if not installation_id or not isinstance(installation_id, str):
            return _error("missing_params")
        # Do not require ``current_team`` to match: OAuth completes in a browser
        # session whose active team may differ from the app that started the flow.
        if not Integration.objects.filter(
            kind="github", integration_id=installation_id, team__in=request.user.teams.all()
        ).exists():
            return _error("invalid_installation")
        installation_ids = [installation_id]
    elif team_oauth_flow:
        # Triggered when the GitHub App is already installed on the org but no PostHog
        # team has captured it (orphan installation). The frontend redirects the user
        # through GitHub's User OAuth so we get a `code` for verify_user_installation_access.
        installation_id = state_payload.get("installation_id")
        team_oauth_team_id = state_payload.get("team_id")
        team_oauth_next = state_payload.get("next") or None
        if not installation_id or not isinstance(installation_id, str):
            return _error("missing_params")
        if not isinstance(team_oauth_team_id, int):
            return _error("invalid_state")
        # Confirm the user still has access to the team they started this flow from.
        if not request.user.teams.filter(id=team_oauth_team_id).exists():
            return _error("invalid_team")
        installation_ids = [installation_id]
    elif oauth_discover_flow:
        pass
    else:
        installation_id = request.GET.get("installation_id")
        if not installation_id:
            return _error("missing_params")
        installation_ids = [installation_id]

    # Exchange code for user-to-server tokens
    if oauth_flow or oauth_discover_flow or team_oauth_flow:
        authorization = GitHubIntegration.github_user_from_code(code, redirect_uri=github_oauth_redirect_uri())
    else:
        authorization = GitHubIntegration.github_user_from_code(code)
    if authorization is None:
        return _error("exchange_failed")

    if oauth_discover_flow:
        try:
            installation_ids = _github_user_installation_ids(authorization.access_token)
        except requests.RequestException:
            return _error("installation_fetch_failed")
        if not installation_ids:
            return _redirect_to_github_app_install(
                request.user,
                "posthog_code" if posthog_code_flow else cast(str | None, state_payload.get("connect_from")),
            )

    for installation_id in installation_ids:
        # installation_id must be a plain positive integer (GitHub App IDs always are).
        # Reject anything else before it touches URL construction.
        if not re.fullmatch(r"\d{1,20}", str(installation_id)):
            return _error("invalid_installation_id")

    for installation_id in installation_ids:
        installation_id = str(installation_id)
        # Verify the authorizing user actually has access to this installation.
        # An attacker could use their own OAuth code with someone else's installation_id
        # to obtain an installation token scoped to a different organisation's repos.
        if not oauth_discover_flow:
            try:
                has_access = GitHubIntegration.verify_user_installation_access(
                    installation_id, authorization.access_token
                )
            except requests.RequestException:
                logger.warning(
                    "github_link: installation ownership check failed",
                    installation_id=installation_id,
                    user_id=request.user.id,
                    exc_info=True,
                )
                return _error("installation_verify_failed")
            if not has_access:
                logger.warning(
                    "github_link: user does not have access to installation",
                    installation_id=installation_id,
                    user_id=request.user.id,
                )
                return _error("installation_not_authorized")

        # Get installation info and access token
        try:
            installation_info = GitHubIntegration.client_request(f"installations/{installation_id}").json()
            access_token_response = GitHubIntegration.client_request(
                f"installations/{installation_id}/access_tokens", method="POST"
            ).json()
        except Exception:
            logger.warning("github_link: failed to fetch installation info", exc_info=True)
            return _error("installation_fetch_failed")

        installation_access_token = access_token_response.get("token")
        if not installation_access_token:
            return _error("installation_token_failed")

        token_expires_at = access_token_response.get("expires_at")
        if not token_expires_at:
            return _error("installation_token_failed")

        user_github_integration_from_installation(
            request.user,
            GitHubInstallationAccess(
                installation_id=installation_id,
                installation_info=installation_info,
                access_token=installation_access_token,
                token_expires_at=token_expires_at,
                repository_selection=access_token_response.get("repository_selection", "selected"),
            ),
            authorization,
        )

    if team_oauth_flow and team_oauth_team_id is not None:
        installation_id = str(installation_ids[0])
        # Create the team-level Integration that the user originally tried to install.
        # ``integration_from_installation_id`` re-fetches the installation token, so it
        # works whether or not another team in the org has already linked this install.
        try:
            team_integration = GitHubIntegration.integration_from_installation_id(
                installation_id, team_oauth_team_id, cast(User, request.user)
            )
        except Exception:
            logger.warning(
                "github_link: failed to create team integration",
                installation_id=installation_id,
                team_id=team_oauth_team_id,
                exc_info=True,
            )
            return _error("integration_create_failed")

        # Mirror the fresh-install flow: stamp the connecting user's GitHub login on
        # the team integration card.
        team_integration.config["connecting_user_github_login"] = authorization.gh_login
        team_integration.save(update_fields=["config"])

        target = team_oauth_next or PERSONAL_INTEGRATIONS_SETTINGS_PATH
        forwarded_params: dict[str, str] = {
            "installation_id": installation_id,
            "integration_id": str(team_integration.id),
        }
        joiner = "&" if "?" in target else "?"
        return redirect(f"{target}{joiner}{urlencode(forwarded_params)}")

    if posthog_code_flow:
        return redirect(f"{ACCOUNT_CONNECTED_GITHUB_INTEGRATION_PATH}?{urlencode({'provider': 'github'})}")
    return redirect(f"{PERSONAL_INTEGRATIONS_SETTINGS_PATH}?github_link_success=1")


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


def _attempt_posthog_code_oauth_fast_path(user: User, team: Any, token: str, state: str) -> Response | None:
    """If the team has a GitHub installation the user hasn't linked yet, return
    an OAuth-only ``/login/oauth/authorize`` redirect so PostHog Code users
    authorize and return immediately — no org picker needed.

    Returns ``None`` when the fast path doesn't apply (no team integration,
    user already linked, or missing config).
    """
    team_installation_id = _team_github_installation_id(team)
    if team_installation_id is None:
        return None
    if UserIntegration.objects.filter(user=user, kind="github", integration_id=team_installation_id).exists():
        return None
    cache.set(
        f"{GITHUB_INSTALL_STATE_CACHE_PREFIX}{token}",
        {
            "user_id": user.id,
            "installation_id": team_installation_id,
            "flow": "oauth_authorize",
            "connect_from": "posthog_code",
        },
        timeout=GITHUB_INSTALL_STATE_TTL_SECONDS,
    )
    return Response({"install_url": _github_oauth_authorize_url(state), "connect_flow": "oauth_authorize"})


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
