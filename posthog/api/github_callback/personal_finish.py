from typing import cast
from urllib.parse import parse_qs, urlencode

from django.core.cache import cache
from django.http import HttpRequest
from django.utils.crypto import get_random_string

import requests
import structlog

from posthog.api.github_callback import state
from posthog.api.github_callback.installation_events import purge_installation_rows
from posthog.api.github_callback.types import (
    FinishResult,
    FlowKind,
    GitHubAuthorizeState,
    github_app_install_url,
    github_oauth_authorize_url,
    github_oauth_redirect_uri,
    is_valid_github_installation_id,
)
from posthog.models import User
from posthog.models.integration import GitHubInstallationAccessFetchError, GitHubIntegration, Integration
from posthog.models.user_integration import (
    UserIntegration,
    refresh_user_github_installation_access,
    user_github_integration_from_installation,
)

logger = structlog.get_logger(__name__)


def _github_state_token(state_raw: str) -> str:
    state_params = parse_qs(state_raw)
    return state_params["token"][0] if "token" in state_params else state_raw


def finish_personal(request: HttpRequest) -> FinishResult:
    """Complete personal GitHub App install or OAuth flows."""
    user = cast(User, request.user)
    connect_from_value: str | None = None

    def _error(reason: str) -> FinishResult:
        logger.warning("github_link: redirecting with error", reason=reason, user_id=user.id)
        return FinishResult(redirect_kind="personal_finish", connect_from=connect_from_value, error=reason)

    code = request.GET.get("code")
    state_raw = request.GET.get("state")

    if not state_raw:
        return _error("missing_params")

    token = _github_state_token(state_raw)
    authorize_state = state.consume_authorize_state(token, user_id=user.id)
    if authorize_state is None:
        return _error("invalid_state")

    connect_from_value = authorize_state.connect_from
    flow = authorize_state.flow
    installation_ids: list[str] = []

    if not code:
        # GitHub omits the OAuth `code` when the App is already installed on the
        # account: the install URL returns a setup update (installation_id, no code)
        # instead of a fresh-install authorization. Bounce through OAuth-discover to
        # mint a code, then link the installation(s) the user can already access.
        if flow == FlowKind.PERSONAL_INSTALL and request.GET.get("installation_id"):
            discover_token = get_random_string(48)
            discover_state = urlencode({"token": discover_token, "source": "user_integration"})
            state.store_unified_authorize_state(
                GitHubAuthorizeState(
                    token=discover_token,
                    flow=FlowKind.OAUTH_DISCOVER,
                    user_id=user.id,
                    connect_from=connect_from_value,
                ),
            )
            return FinishResult(redirect_kind="oauth_url", oauth_url=github_oauth_authorize_url(discover_state))
        return _error("missing_params")

    match flow:
        case FlowKind.PERSONAL_OAUTH:
            installation_id = authorize_state.installation_id
            if not installation_id:
                return _error("missing_params")
            if not Integration.objects.filter(
                kind="github", integration_id=installation_id, team__in=user.teams.all()
            ).exists():
                return _error("invalid_installation")
            installation_ids = [installation_id]
        case FlowKind.TEAM_OAUTH:
            installation_id = authorize_state.installation_id
            if not installation_id:
                return _error("missing_params")
            if authorize_state.team_id is None:
                return _error("invalid_state")
            # `user.teams` membership is no longer re-checked here — losing access between
            # OAuth-trigger and OAuth-return is a rare timing edge case. If it happens,
            # `integration_from_installation_id` below will raise rather than emit a typed code.
            installation_ids = [installation_id]
        case FlowKind.OAUTH_DISCOVER:
            pass
        case _:
            installation_id = request.GET.get("installation_id")
            if not installation_id:
                return _error("missing_params")
            installation_ids = [installation_id]

    if flow.is_oauth_redirect:
        authorization = GitHubIntegration.github_user_from_code(code, redirect_uri=github_oauth_redirect_uri())
    else:
        authorization = GitHubIntegration.github_user_from_code(code)
    if authorization is None:
        return _error("exchange_failed")

    if flow.discovers_installations:
        try:
            response = requests.get(
                "https://api.github.com/user/installations",
                headers={
                    "Accept": "application/vnd.github+json",
                    "Authorization": f"Bearer {authorization.access_token}",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
                params={"per_page": 100},
                timeout=10,
            )
            if response.status_code != 200:
                logger.warning("github_link: failed to list user installations", status_code=response.status_code)
                raise requests.RequestException(f"Unexpected status {response.status_code} listing user installations")
            installations = response.json().get("installations", [])
            installation_ids = []
            if isinstance(installations, list):
                for installation in installations:
                    if isinstance(installation, dict) and installation.get("id") is not None:
                        installation_ids.append(str(installation["id"]))
        except requests.RequestException:
            return _error("installation_fetch_failed")
        if not installation_ids:
            token = get_random_string(48)
            state_query = urlencode({"token": token, "source": "user_integration"})
            state.store_unified_authorize_state(
                GitHubAuthorizeState(
                    token=token,
                    flow=FlowKind.PERSONAL_INSTALL,
                    user_id=user.id,
                    connect_from=connect_from_value,
                ),
            )
            return FinishResult(
                redirect_kind="oauth_url",
                oauth_url=github_app_install_url(state_query),
            )

    for installation_id in installation_ids:
        if not is_valid_github_installation_id(installation_id):
            return _error("invalid_installation_id")

    for installation_id in installation_ids:
        installation_id = str(installation_id)
        if not flow.discovers_installations:
            try:
                has_access = GitHubIntegration.verify_user_installation_access(
                    installation_id, authorization.access_token
                )
            except requests.RequestException:
                logger.warning(
                    "github_link: installation ownership check failed",
                    installation_id=installation_id,
                    user_id=user.id,
                    exc_info=True,
                )
                return _error("installation_verify_failed")
            if not has_access:
                logger.warning(
                    "github_link: user does not have access to installation",
                    installation_id=installation_id,
                    user_id=user.id,
                )
                if flow == FlowKind.PERSONAL_OAUTH:
                    healed = _restart_install_for_dead_installation(user, installation_id, authorize_state)
                    if healed is not None:
                        return healed
                return _error("installation_not_authorized")

        try:
            installation_access = GitHubIntegration.fetch_installation_access(installation_id)
        except GitHubInstallationAccessFetchError as exc:
            if exc.code == "installation_fetch_failed":
                logger.warning("github_link: failed to fetch installation info", exc_info=True)
            return _error(exc.code)

        user_github_integration_from_installation(user, installation_access, authorization)

    if flow.creates_team_integration and authorize_state.team_id is not None:
        installation_id = str(installation_ids[0])
        try:
            team_integration = GitHubIntegration.integration_from_installation_id(
                installation_id, authorize_state.team_id, user
            )
        except (GitHubInstallationAccessFetchError, requests.RequestException):
            logger.warning(
                "github_link: failed to create team integration",
                installation_id=installation_id,
                team_id=authorize_state.team_id,
                exc_info=True,
            )
            return _error("integration_create_failed")

        team_integration.config["connecting_user_github_login"] = authorization.gh_login
        team_integration.save(update_fields=["config"])

        return FinishResult(
            redirect_kind="team_oauth_success",
            next_url=authorize_state.next_url,
            installation_id=installation_id,
            integration_id=str(team_integration.id),
        )

    return FinishResult(redirect_kind="personal_finish", connect_from=connect_from_value)


def _restart_install_for_dead_installation(
    user: User, installation_id: str, authorize_state: GitHubAuthorizeState
) -> FinishResult | None:
    """Self-healing for a stale fast path: PERSONAL_OAUTH is the one flow whose installation id
    comes from our database, which can outlive the GitHub installation when an uninstall webhook
    is missed. When GitHub confirms the installation is gone, purge the stale rows and restart
    the team install flow instead of dead-ending. Returns None when the installation is alive
    (the user genuinely lacks access) or the probe is inconclusive."""
    if authorize_state.team_id is None:
        return None
    try:
        probe = GitHubIntegration.client_request(f"installations/{installation_id}")
    except Exception:
        logger.warning("github_link: stale-installation probe failed", installation_id=installation_id, exc_info=True)
        return None
    if probe.status_code != 404:
        return None
    team_deleted, user_deleted = purge_installation_rows(installation_id)
    logger.info(
        "github_link: installation gone on GitHub, purged stale rows and restarting install flow",
        installation_id=installation_id,
        user_id=user.id,
        team_integrations_deleted=team_deleted,
        user_integrations_deleted=user_deleted,
    )
    token = get_random_string(48)
    state.store_unified_authorize_state(
        GitHubAuthorizeState(
            token=token,
            flow=FlowKind.TEAM_INSTALL,
            user_id=user.id,
            team_id=authorize_state.team_id,
            next_url=authorize_state.next_url,
        ),
    )
    return FinishResult(
        redirect_kind="oauth_url",
        oauth_url=github_app_install_url(urlencode({"next": authorize_state.next_url or "", "token": token})),
    )


def finish_personal_setup_update(request: HttpRequest) -> FinishResult:
    """Refresh a personal UserIntegration after GitHub installation settings change."""
    user = cast(User, request.user)
    installation_id = request.GET.get("installation_id")

    def _error(reason: str) -> FinishResult:
        logger.warning("github_link: personal setup update failed", reason=reason, user_id=user.id)
        return FinishResult(redirect_kind="personal_finish", connect_from=None, error=reason)

    if not is_valid_github_installation_id(installation_id):
        return _error("invalid_installation_id")

    installation_id = str(installation_id)
    try:
        integration = UserIntegration.objects.get(
            user=user,
            kind=UserIntegration.IntegrationKind.GITHUB,
            integration_id=installation_id,
        )
    except UserIntegration.DoesNotExist:
        return _error("invalid_installation")

    try:
        installation_access = GitHubIntegration.fetch_installation_access(installation_id)
    except GitHubInstallationAccessFetchError as exc:
        if exc.code == "installation_fetch_failed":
            logger.warning(
                "github_link: failed to refresh installation after update",
                installation_id=installation_id,
                user_id=user.id,
                exc_info=True,
            )
        return _error(exc.code)

    refresh_user_github_installation_access(integration, installation_access)

    # Burn the pending authorize state so a repeated GitHub setup-URL ping within
    # the 5-minute TTL doesn't re-run the refresh.
    pending_token = cache.get(state.unified_authorize_pending_cache_key(user.id))
    if pending_token:
        state.consume_authorize_state(str(pending_token), user_id=user.id)

    return FinishResult(redirect_kind="personal_finish", connect_from=None)
