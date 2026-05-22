"""GitHub OAuth helpers shared by callback finish logic."""

from __future__ import annotations

import requests

from posthog.api.github_callback.types import github_oauth_redirect_uri
from posthog.models.integration import GitHubIntegration, GitHubUserAuthorization


def exchange_user_authorization(code: str, *, use_oauth_redirect_uri: bool) -> GitHubUserAuthorization | None:
    if use_oauth_redirect_uri:
        return GitHubIntegration.github_user_from_code(code, redirect_uri=github_oauth_redirect_uri())
    return GitHubIntegration.github_user_from_code(code)


def verify_user_installation_access(installation_id: str, user_access_token: str) -> bool:
    return GitHubIntegration.verify_user_installation_access(installation_id, user_access_token)


def verify_user_installation_access_or_raise(installation_id: str, user_access_token: str) -> None:
    try:
        has_access = verify_user_installation_access(installation_id, user_access_token)
    except requests.RequestException:
        raise
    if not has_access:
        raise PermissionError("installation_not_authorized")
