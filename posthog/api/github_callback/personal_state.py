"""State and URL helpers for the personal GitHub linking flow.

The personal flow keeps a small JSON blob in the cache, keyed by a random
``token``, that we look up when GitHub redirects back to us. Some helpers also
build the off-host GitHub URLs (install page, user OAuth page) the user is
sent to.
"""

from typing import Any
from urllib.parse import parse_qs, urlencode

from django.conf import settings
from django.core.cache import cache
from django.http import HttpResponseRedirect
from django.shortcuts import redirect
from django.utils.crypto import get_random_string

import requests
import structlog
from rest_framework import exceptions

from posthog.api.github_callback.types import (
    GITHUB_INSTALL_STATE_CACHE_PREFIX,
    GITHUB_INSTALL_STATE_TTL_SECONDS,
    github_oauth_redirect_uri,
)
from posthog.models.instance_setting import get_instance_settings
from posthog.models.user import User

logger = structlog.get_logger(__name__)


def github_state_token(state_raw: str) -> str:
    """Pull the random token out of ``state``.

    The frontend extracts the raw token from the URL-encoded ``state`` before
    forwarding here, so ``state_raw`` is normally the 48-char random token.
    Handle both forms so direct backend calls (e.g. in tests) and any future
    flow changes work correctly.
    """
    state_params = parse_qs(state_raw)
    return state_params["token"][0] if "token" in state_params else state_raw


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
    """Build the GitHub App install URL."""
    instance_settings = get_instance_settings(["GITHUB_APP_SLUG"])
    app_slug = instance_settings.get("GITHUB_APP_SLUG")
    if not app_slug:
        raise exceptions.ValidationError("GitHub App is not configured on this instance (missing GITHUB_APP_SLUG).")
    return f"https://github.com/apps/{app_slug}/installations/new?{urlencode({'state': state})}"


def github_oauth_authorize_url(state: str) -> str:
    """Build the GitHub App user authorization URL."""
    if not settings.GITHUB_APP_CLIENT_ID:
        raise exceptions.ValidationError("GitHub App client ID is not configured (GITHUB_APP_CLIENT_ID missing).")
    return "https://github.com/login/oauth/authorize?" + urlencode(
        {"client_id": settings.GITHUB_APP_CLIENT_ID, "redirect_uri": github_oauth_redirect_uri(), "state": state}
    )


def redirect_to_github_app_install(user: User, connect_from: str | None) -> HttpResponseRedirect:
    """Continue from user OAuth discovery to app installation when no installation exists yet."""
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
    return redirect(github_app_install_url(state))
