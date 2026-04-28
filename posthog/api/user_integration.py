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

from posthog.api.integration import GitHubReposQuerySerializer, GitHubReposResponseSerializer
from posthog.auth import (
    OAuthAccessTokenAuthentication,
    PersonalAPIKeyAuthentication,
    SessionAuthentication,
    session_auth_required,
)
from posthog.models.instance_setting import get_instance_settings
from posthog.models.integration import GitHubInstallationAccess, GitHubIntegration, Integration
from posthog.models.user import User
from posthog.models.user_integration import (
    UserGitHubIntegration,
    UserIntegration,
    user_github_integration_from_installation,
)
from posthog.permissions import APIScopePermission
from posthog.rate_limit import UserAuthenticationThrottle

logger = structlog.get_logger(__name__)

GITHUB_INSTALL_STATE_CACHE_PREFIX = "github_user_install_state:"
GITHUB_INSTALL_STATE_TTL_SECONDS = 10 * 60

# Frontend route for the personal Settings → Personal integrations section.
PERSONAL_INTEGRATIONS_SETTINGS_PATH = "/settings/user-personal-integrations"
# PostHog Code: personal GitHub integration complete → web → deep-link (see ``AccountConnected`` / ``github-integration``).
ACCOUNT_CONNECTED_GITHUB_INTEGRATION_PATH = "/account-connected/github-integration"


def _github_oauth_redirect_uri() -> str:
    """Callback URL registered on the GitHub App; must match the authorize request."""
    return f"{settings.SITE_URL.rstrip('/')}/complete/github-link/"


def _connect_from_github_start(request: Request) -> str | None:
    """Optional ``connect_from`` from JSON body (e.g. PostHog Code)."""
    data: Any = request.data
    if not isinstance(data, dict):
        return None
    raw = data.get("connect_from")
    if raw == "posthog_code":
        return "posthog_code"
    return None


def _team_for_github_start(user: User, request: Request):
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


def _serialize_github_integration(
    integration: UserIntegration,
    *,
    team_integration_installation_ids: set[str],
) -> dict[str, Any]:
    """Build the response payload for a single GitHub UserIntegration."""
    return {
        "kind": "github",
        "installation_id": integration.integration_id,
        "repository_selection": integration.config.get("repository_selection"),
        "account": integration.config.get("account"),
        "uses_shared_installation": integration.integration_id in team_integration_installation_ids,
        "created_at": integration.created_at,
    }


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
        help_text="oauth_authorize when using user OAuth against an existing team installation; app_install for the GitHub App installation UI.",
    )


@extend_schema(tags=["core"])
class UserIntegrationViewSet(viewsets.GenericViewSet):
    """`/api/users/@me/integrations/` — manage the user's personal GitHub integrations."""

    scope_object = "user"
    required_scopes: list[str] | None = None
    scope_object_read_actions = ["list", "retrieve", "github_repos"]
    scope_object_write_actions = [
        "create",
        "update",
        "partial_update",
        "patch",
        "destroy",
        "github_start",
        "github_destroy",
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

        - If the current project has **no** team-level GitHub ``Integration``, returns
          ``install_url`` pointing at ``/installations/new`` (configure org + repos).
        - If the team **already** has a GitHub installation, returns ``install_url``
          pointing at ``/login/oauth/authorize`` so the user only authorizes as
          themselves for that installation (no repo scoping UI on GitHub).

        In both cases the response key is ``install_url`` for compatibility with callers.
        """
        from django.utils.crypto import get_random_string

        token = get_random_string(48)
        state = urlencode({"token": token, "source": "user_integration"})
        user = self._get_user()
        team = _team_for_github_start(user, self.request)
        connect_from = _connect_from_github_start(self.request)

        has_team_github = False
        team_installation_id: str | None = None
        if team is not None:
            team_row = (
                Integration.objects.filter(team=team, kind="github")
                .exclude(integration_id__isnull=True)
                .exclude(integration_id="")
                .order_by("id")
                .first()
            )
            if team_row is not None and team_row.integration_id:
                has_team_github = True
                team_installation_id = str(team_row.integration_id)

        if has_team_github and team_installation_id:
            client_id = settings.GITHUB_APP_CLIENT_ID
            if not client_id:
                raise exceptions.ValidationError(
                    "GitHub App client ID is not configured (GITHUB_APP_CLIENT_ID missing)."
                )
            oauth_state_payload: dict[str, Any] = {
                "user_id": user.id,
                "installation_id": team_installation_id,
                "flow": "oauth_authorize",
            }
            if connect_from:
                oauth_state_payload["connect_from"] = connect_from
            cache.set(
                f"{GITHUB_INSTALL_STATE_CACHE_PREFIX}{token}",
                oauth_state_payload,
                timeout=GITHUB_INSTALL_STATE_TTL_SECONDS,
            )
            redirect_uri = _github_oauth_redirect_uri()
            install_url = "https://github.com/login/oauth/authorize?" + urlencode(
                {"client_id": client_id, "redirect_uri": redirect_uri, "state": state}
            )
            return Response({"install_url": install_url, "connect_flow": "oauth_authorize"})

        instance_settings = get_instance_settings(["GITHUB_APP_SLUG"])
        app_slug = instance_settings.get("GITHUB_APP_SLUG")
        if not app_slug:
            raise exceptions.ValidationError("GitHub App is not configured on this instance (missing GITHUB_APP_SLUG).")

        install_state_payload: dict[str, Any] = {"user_id": user.id}
        if connect_from:
            install_state_payload["connect_from"] = connect_from
        cache.set(
            f"{GITHUB_INSTALL_STATE_CACHE_PREFIX}{token}",
            install_state_payload,
            timeout=GITHUB_INSTALL_STATE_TTL_SECONDS,
        )
        params = urlencode({"state": state})
        return Response(
            {
                "install_url": f"https://github.com/apps/{app_slug}/installations/new?{params}",
                "connect_flow": "app_install",
            }
        )


def _posthog_code_flow_from_state_query(request: HttpRequest) -> bool:
    """Best-effort: OAuth error callbacks may still include ``state``; read cache (do not delete)."""
    state_raw = request.GET.get("state")
    if not state_raw:
        return False
    state_params = parse_qs(state_raw)
    if "token" in state_params:
        token = state_params["token"][0]
    else:
        token = state_raw
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
    state_params = parse_qs(state_raw)
    if "token" in state_params:
        token = state_params["token"][0]
    else:
        token = state_raw

    # Validate state
    cache_key = f"{GITHUB_INSTALL_STATE_CACHE_PREFIX}{token}"
    state_payload = cache.get(cache_key)
    if not state_payload or state_payload.get("user_id") != request.user.id:
        return _error("invalid_state")
    if state_payload.get("connect_from") == "posthog_code":
        posthog_code_flow = True
    cache.delete(cache_key)

    oauth_flow = state_payload.get("flow") == "oauth_authorize"
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
    else:
        installation_id = request.GET.get("installation_id")
        if not installation_id:
            return _error("missing_params")

    # installation_id must be a plain positive integer (GitHub App IDs always are).
    # Reject anything else before it touches URL construction.
    if not re.fullmatch(r"\d{1,20}", str(installation_id)):
        return _error("invalid_installation_id")

    installation_id = str(installation_id)

    # Exchange code for user-to-server tokens
    if oauth_flow:
        authorization = GitHubIntegration.github_user_from_code(code, redirect_uri=_github_oauth_redirect_uri())
    else:
        authorization = GitHubIntegration.github_user_from_code(code)
    if authorization is None:
        return _error("exchange_failed")

    # Verify the authorizing user actually has access to this installation.
    # An attacker could use their own OAuth code with someone else's installation_id
    # to obtain an installation token scoped to a different organisation's repos.
    try:
        verify_response = requests.get(  # nosemgrep: python.django.security.injection.ssrf.ssrf-injection-requests.ssrf-injection-requests -- installation_id is validated as digits-only above
            f"https://api.github.com/user/installations/{installation_id}/repositories",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {authorization.access_token}",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            params={"per_page": 1},
            timeout=10,
        )
    except requests.RequestException:
        logger.warning("github_link: installation ownership check request failed", exc_info=True)
        return _error("installation_verify_failed")

    if verify_response.status_code == 404:
        logger.warning(
            "github_link: user does not have access to installation",
            installation_id=installation_id,
            user_id=request.user.id,
        )
        return _error("installation_not_authorized")
    if verify_response.status_code != 200:
        logger.warning(
            "github_link: unexpected status verifying installation access",
            installation_id=installation_id,
            user_id=request.user.id,
            status_code=verify_response.status_code,
        )
        return _error("installation_verify_failed")

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

    if posthog_code_flow:
        return redirect(f"{ACCOUNT_CONNECTED_GITHUB_INTEGRATION_PATH}?{urlencode({'provider': 'github'})}")
    return redirect(f"{PERSONAL_INTEGRATIONS_SETTINGS_PATH}?github_link_success=1")
