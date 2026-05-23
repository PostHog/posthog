from urllib.parse import parse_qs, parse_qsl, urlencode

from django.conf import settings
from django.http import HttpRequest, HttpResponseRedirect
from django.shortcuts import redirect
from django.utils.crypto import get_random_string

import requests
import structlog
from rest_framework import exceptions

from posthog.api.github_callback import state as github_callback_state
from posthog.api.github_callback.types import (
    APP_CONNECT_FROM_VALUES,
    FlowKind,
    GitHubAuthorizeState,
    github_oauth_redirect_uri,
)
from posthog.models.instance_setting import get_instance_settings
from posthog.models.user import User

logger = structlog.get_logger(__name__)


def github_state_token(state_raw: str) -> str:
    state_params = parse_qs(state_raw)
    return state_params["token"][0] if "token" in state_params else state_raw


def is_personal_github_setup_state(state_raw: str | None) -> bool:
    """True when GitHub's Setup URL callback belongs to a personal UserIntegration flow."""
    if not state_raw:
        return False
    return dict(parse_qsl(state_raw)).get("source") == "user_integration"


def github_user_installation_ids(user_access_token: str) -> list[str]:
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


def github_app_install_url(state: str) -> str:
    instance_settings = get_instance_settings(["GITHUB_APP_SLUG"])
    app_slug = instance_settings.get("GITHUB_APP_SLUG")
    if not app_slug:
        raise exceptions.ValidationError("GitHub App is not configured on this instance (missing GITHUB_APP_SLUG).")
    return f"https://github.com/apps/{app_slug}/installations/new?{urlencode({'state': state})}"


def redirect_to_github_app_install(user: User, connect_from: str | None) -> HttpResponseRedirect:
    """Continue from user OAuth discovery to app installation when no installation exists yet."""
    token = get_random_string(48)
    state_query = urlencode({"token": token, "source": "user_integration"})
    github_callback_state.store_personal_authorize_state(
        GitHubAuthorizeState(
            token=token,
            flow=FlowKind.PERSONAL_INSTALL,
            user_id=user.id,
            connect_from=connect_from,
        ),
    )
    return redirect(github_app_install_url(state_query))


def app_connect_from_from_state_query(request: HttpRequest) -> str | None:
    """Best-effort: OAuth error callbacks may still include ``state``; read cache
    (do not delete) to recover which first-party client started the flow."""
    state_raw = request.GET.get("state")
    if not state_raw:
        return None
    token = github_state_token(state_raw)
    authorize_state = github_callback_state.load_authorize_state(token, user_id=request.user.id)
    if authorize_state is None:
        return None
    connect_from = authorize_state.connect_from
    return connect_from if connect_from in APP_CONNECT_FROM_VALUES else None


def github_oauth_authorize_url(state: str) -> str:
    if not settings.GITHUB_APP_CLIENT_ID:
        raise exceptions.ValidationError("GitHub App client ID is not configured (GITHUB_APP_CLIENT_ID missing).")
    return "https://github.com/login/oauth/authorize?" + urlencode(
        {"client_id": settings.GITHUB_APP_CLIENT_ID, "redirect_uri": github_oauth_redirect_uri(), "state": state}
    )
