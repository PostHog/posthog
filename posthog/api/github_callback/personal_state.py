"""Read-only helpers for a user's *personal* GitHub App state.

Distinct from ``team_services.py``, which manages team-scoped ``Integration`` rows: this module
answers what a user's own OAuth-linked ``UserIntegration`` can see on GitHub, independent of any
team. Shared by the personal "unlinked installations" check, the org installation picker, and
orphan-installation adoption.
"""

from typing import Any

import requests

from posthog.egress.github.transport import GitHubEgressBudgetExhausted, github_request
from posthog.models.user import User
from posthog.models.user_integration import UserGitHubIntegration, UserIntegration

_OBSERVABILITY_SOURCE = "integration"


def _newest_personal_github_integration(user: User) -> UserIntegration | None:
    return (
        UserIntegration.objects.filter(user=user, kind="github")
        .exclude(sensitive_config={})
        .order_by("-created_at")
        .first()
    )


def user_has_personal_github_integration(user: User) -> bool:
    """Whether ``user`` has a usable personal GitHub App link at all."""
    return _newest_personal_github_integration(user) is not None


def personal_github_login(user: User) -> str | None:
    """The user's own GitHub login from their most recent personal GitHub link, if any."""
    integration = _newest_personal_github_integration(user)
    if integration is None:
        return None
    return UserGitHubIntegration(integration).github_login


def usable_personal_github_token(user: User) -> str | None:
    """Return a usable user-to-server GitHub token for ``user``, refreshing it if needed.

    Tries every personal GitHub link newest-first, since the newest row can hold stale credentials
    while an older one still refreshes fine. Returns None when no link yields a token — callers
    must treat this as "can't verify" rather than raise, since a stale personal link is common and
    not itself an error.
    """
    integrations = (
        UserIntegration.objects.filter(user=user, kind="github").exclude(sensitive_config={}).order_by("-created_at")
    )
    for integration in integrations:
        try:
            token = UserGitHubIntegration(integration).get_usable_user_access_token()
        except Exception:
            continue
        if token:
            return token
    return None


def list_user_github_app_installations(user: User) -> list[dict[str, Any]] | None:
    """List the GitHub App installations visible to ``user``'s personal OAuth token.

    Returns installation dicts as GitHub reports them from ``GET /user/installations`` (``id``,
    ``account`` with ``login``/``type``, etc.), or None when the check can't be answered — no
    personal GitHub link, a token refresh failure, a network error, or a non-200 response. Callers
    must treat None as "unknown" and degrade gracefully rather than fail the request.
    """
    token = usable_personal_github_token(user)
    if token is None:
        return None

    try:
        # Identity-blind: user OAuth token, metered against the user's budget, not an installation's.
        response = github_request(
            "GET",
            "https://api.github.com/user/installations",
            source=_OBSERVABILITY_SOURCE,
            headers={"Authorization": f"Bearer {token}"},
            params={"per_page": 100},
            timeout=10,
        )
    except (requests.RequestException, GitHubEgressBudgetExhausted):
        return None

    if response.status_code != 200:
        return None

    try:
        installations = response.json().get("installations", [])
    except ValueError:
        return None

    if not isinstance(installations, list):
        return None

    return [
        installation
        for installation in installations
        if isinstance(installation, dict) and installation.get("id") is not None
    ]
