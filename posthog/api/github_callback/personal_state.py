"""Read-only helpers for a user's *personal* GitHub App state.

Distinct from ``team_services.py``, which manages team-scoped ``Integration`` rows: this module
answers what a user's own OAuth-linked ``UserIntegration`` can see on GitHub, independent of any
team. Shared by the personal "unlinked installations" check, the org installation picker, and
orphan-installation adoption.
"""

from dataclasses import field
from typing import Any

import requests

from posthog.dataclasses import frozen
from posthog.egress.github.transport import GitHubEgressBudgetExhausted, github_request
from posthog.models.integration.github_audit import GitHubAudit
from posthog.models.user import User
from posthog.models.user_integration import UserGitHubIntegration, UserIntegration

_OBSERVABILITY_SOURCE = "integration"


@frozen
class PersonalGitHubCredential:
    token: str = field(repr=False)
    integration: UserIntegration = field(repr=False)


@frozen(frozen=False)
class PersonalGitHubDiscovery:
    audit: GitHubAudit
    discovery_id: str
    login: str | None = None
    status: str = "not_connected"


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


def usable_personal_github_credential(user: User) -> PersonalGitHubCredential | None:
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
            return PersonalGitHubCredential(token=token, integration=integration)
    return None


def usable_personal_github_token(user: User) -> str | None:
    credential = usable_personal_github_credential(user)
    return credential.token if credential else None


def list_user_github_app_installations(
    user: User, discovery: PersonalGitHubDiscovery | None = None
) -> list[dict[str, Any]] | None:
    """List the GitHub App installations visible to ``user``'s personal OAuth token.

    Returns installation dicts as GitHub reports them from ``GET /user/installations`` (``id``,
    ``account`` with ``login``/``type``, etc.), or None when the check can't be answered — no
    personal GitHub link, a token refresh failure, a network error, or a non-200 response. Callers
    must treat None as "unknown" and degrade gracefully rather than fail the request.
    """
    credential = usable_personal_github_credential(user)
    connected = user_has_personal_github_integration(user)
    if discovery:
        discovery.status = "unavailable" if connected else "not_connected"
    if credential is None:
        return None
    token = credential.token
    if discovery:
        discovery.login = UserGitHubIntegration(credential.integration).github_login
        discovery.audit.record(
            "discovery_credential_selected",
            discovery_id=discovery.discovery_id,
            **(GitHubAudit.personal(credential.integration).personal_metadata or {}),
        )

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
        if discovery:
            discovery.audit.record(
                "discovery_failed", discovery_id=discovery.discovery_id, reason="github_request_failed"
            )
        return None

    if discovery:
        discovery.audit.record(
            "discovery_github_response",
            discovery_id=discovery.discovery_id,
            github_status=response.status_code,
            github_request_id=response.headers.get("X-GitHub-Request-Id"),
        )
    if response.status_code != 200:
        return None

    try:
        installations = response.json().get("installations", [])
    except ValueError:
        return None

    if not isinstance(installations, list):
        return None

    if discovery:
        discovery.status = "ok"
        discovery.audit.record(
            "discovery_candidates",
            discovery_id=discovery.discovery_id,
            source="personal",
            candidates=[
                {
                    "installation_id": str(item["id"]),
                    "account_name": (item.get("account") or {}).get("login"),
                    "account_type": (item.get("account") or {}).get("type"),
                }
                for item in installations
                if isinstance(item, dict) and item.get("id") is not None
            ],
        )

    return [
        installation
        for installation in installations
        if isinstance(installation, dict) and installation.get("id") is not None
    ]
