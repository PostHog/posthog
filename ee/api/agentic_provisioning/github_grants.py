"""Server-side store for GitHub user authorizations minted during a partner drop flow.

A partner (e.g. posthog.com) exchanges a GitHub OAuth code via the provisioning API and
receives only an opaque ``grant_id`` — the GitHub user-to-server tokens never leave
PostHog. The grant is later consumed when the GitHub installation is linked to a team
(the ``github_integration`` resource action or the ``configuration.wizard`` block in
``account_requests``).

Grants are region-local: they live in this region's cache, so every follow-up call that
references a ``grant_id`` must hit the region that minted it. v1 partners are US-only.
"""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from typing import Any

from django.core.cache import cache
from django.utils import timezone

import requests
import structlog
from cryptography.fernet import InvalidToken

from posthog.egress.github.transport import github_request
from posthog.helpers.encrypted_fields import EncryptedTextField
from posthog.models.integration import GitHubUserAuthorization
from posthog.models.oauth import OAuthApplication

from . import GITHUB_GRANT_CACHE_PREFIX

logger = structlog.get_logger(__name__)

# Long enough to survive the existing-user consent detour (login + in-app approval),
# short enough that a stored user token goes stale quickly if never used.
GITHUB_GRANT_TTL_SECONDS = 3600

# The payload holds GitHub user-to-server tokens, so it is encrypted at rest in the
# cache with the same MultiFernet keys that back EncryptedJSONField columns.
_grant_cipher = EncryptedTextField()


class GitHubEmailAccessDenied(Exception):
    """GitHub refused the /user/emails read — almost always the App missing the
    "Email addresses (read)" account permission, i.e. our misconfiguration.

    Kept distinct from "the user has no verified email" (a legitimate state the
    partner recovers from by collecting an email inline) so the misconfiguration
    stays a loud error instead of silently degrading every drop."""


@dataclass(frozen=True)
class GitHubGrant:
    """A stored GitHub user authorization, bound to the partner that created it."""

    grant_id: str
    partner_id: str
    gh_id: int
    gh_login: str
    email: str | None
    access_token: str
    refresh_token: str | None
    access_token_expires_in: int | None
    refresh_token_expires_in: int | None
    created_at: str

    def to_authorization(self) -> GitHubUserAuthorization:
        return GitHubUserAuthorization(
            gh_id=self.gh_id,
            gh_login=self.gh_login,
            access_token=self.access_token,
            refresh_token=self.refresh_token,
            access_token_expires_in=self.access_token_expires_in,
            refresh_token_expires_in=self.refresh_token_expires_in,
        )

    def cache_payload(self) -> dict[str, Any]:
        return {
            "partner_id": self.partner_id,
            "gh_id": self.gh_id,
            "gh_login": self.gh_login,
            "email": self.email,
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "access_token_expires_in": self.access_token_expires_in,
            "refresh_token_expires_in": self.refresh_token_expires_in,
            "created_at": self.created_at,
        }

    @classmethod
    def from_cache(cls, grant_id: str, payload: dict[str, Any]) -> GitHubGrant:
        return cls(
            grant_id=grant_id,
            partner_id=payload["partner_id"],
            gh_id=payload["gh_id"],
            gh_login=payload["gh_login"],
            email=payload["email"],
            access_token=payload["access_token"],
            refresh_token=payload.get("refresh_token"),
            access_token_expires_in=payload.get("access_token_expires_in"),
            refresh_token_expires_in=payload.get("refresh_token_expires_in"),
            created_at=payload["created_at"],
        )


def create_grant(partner: OAuthApplication, authorization: GitHubUserAuthorization, email: str | None) -> GitHubGrant:
    grant = GitHubGrant(
        grant_id=secrets.token_urlsafe(32),
        partner_id=str(partner.id),
        gh_id=authorization.gh_id,
        gh_login=authorization.gh_login,
        email=email,
        access_token=authorization.access_token,
        refresh_token=authorization.refresh_token,
        access_token_expires_in=authorization.access_token_expires_in,
        refresh_token_expires_in=authorization.refresh_token_expires_in,
        created_at=timezone.now().isoformat(),
    )
    cache.set(
        f"{GITHUB_GRANT_CACHE_PREFIX}{grant.grant_id}",
        _grant_cipher.encrypt(json.dumps(grant.cache_payload())),
        timeout=GITHUB_GRANT_TTL_SECONDS,
    )
    return grant


def load_grant(grant_id: str, partner: OAuthApplication) -> GitHubGrant | None:
    """Load a grant if it exists and was created by ``partner``, else None.

    Partner mismatch deliberately looks identical to a missing grant so the endpoint
    can't be used as an existence oracle for other partners' grants.
    """
    if not grant_id:
        return None
    raw = cache.get(f"{GITHUB_GRANT_CACHE_PREFIX}{grant_id}")
    if raw is None:
        return None
    try:
        payload = json.loads(_grant_cipher.decrypt(raw))
        grant = GitHubGrant.from_cache(grant_id, payload)
    except (InvalidToken, ValueError, KeyError, TypeError):
        logger.warning("github_grant.corrupt_payload", grant_id=grant_id)
        return None
    if grant.partner_id != str(partner.id):
        logger.warning("github_grant.partner_mismatch", grant_id=grant_id, partner_id=str(partner.id))
        return None
    return grant


def consume_grant(grant_id: str) -> None:
    cache.delete(f"{GITHUB_GRANT_CACHE_PREFIX}{grant_id}")


def fetch_primary_email(access_token: str) -> str | None:
    """Fetch the user's primary verified email with a user-to-server token.

    Returns None when the user simply has no verified email (the partner collects one
    inline instead). Raises ``GitHubEmailAccessDenied`` when GitHub refuses the read
    (missing App permission) and ``requests.RequestException`` on network errors or
    GitHub 5xx so callers can distinguish "retry" from "won't work".
    """
    # Identity-blind: user OAuth token, metered against the user's budget.
    response = github_request(
        "GET",
        "https://api.github.com/user/emails",
        source="integration",
        headers={"Authorization": f"Bearer {access_token}"},
        params={"per_page": 100},
        timeout=10,
    )
    if response.status_code >= 500:
        raise requests.RequestException(f"Unexpected status {response.status_code} listing user emails")
    if response.status_code != 200:
        logger.warning("github_grant.user_emails_denied", status_code=response.status_code)
        raise GitHubEmailAccessDenied(f"GitHub returned {response.status_code} listing user emails")
    emails = response.json()
    if not isinstance(emails, list):
        return None
    verified = [e for e in emails if isinstance(e, dict) and e.get("verified") and e.get("email")]
    for entry in verified:
        if entry.get("primary"):
            return str(entry["email"])
    if verified:
        return str(verified[0]["email"])
    return None


# A single page covers the overwhelmingly common case; the cap bounds request fan-out
# for users with huge installations so the endpoint stays cheap to poll.
_REPOSITORY_PAGE_SIZE = 100
_REPOSITORY_MAX_PAGES = 3


def list_installations_and_repositories(access_token: str) -> dict[str, Any]:
    """List the user's installations of our GitHub App and the repos each grants.

    A user-to-server token only ever sees installations of the App that minted it,
    so no app filtering is needed. Raises ``requests.RequestException`` on failure.
    """
    # Identity-blind: user OAuth token, metered against the user's budget.
    response = github_request(
        "GET",
        "https://api.github.com/user/installations",
        source="integration",
        headers={"Authorization": f"Bearer {access_token}"},
        params={"per_page": 100},
        timeout=10,
    )
    if response.status_code != 200:
        logger.warning("github_grant.list_installations_failed", status_code=response.status_code)
        raise requests.RequestException(f"Unexpected status {response.status_code} listing user installations")

    installations: list[dict[str, Any]] = []
    repositories: list[dict[str, Any]] = []
    raw_installations = response.json().get("installations", [])
    if not isinstance(raw_installations, list):
        raw_installations = []

    for installation in raw_installations:
        if not isinstance(installation, dict) or installation.get("id") is None:
            continue
        installation_id = str(installation["id"])
        installations.append(
            {
                "id": installation_id,
                "account_login": (installation.get("account") or {}).get("login"),
                "repository_selection": installation.get("repository_selection"),
            }
        )
        repositories.extend(_list_installation_repositories(access_token, installation_id))

    return {"installations": installations, "repositories": repositories}


def _list_installation_repositories(access_token: str, installation_id: str) -> list[dict[str, Any]]:
    repositories: list[dict[str, Any]] = []
    for page in range(1, _REPOSITORY_MAX_PAGES + 1):
        response = github_request(
            "GET",
            f"https://api.github.com/user/installations/{installation_id}/repositories",
            source="integration",
            headers={"Authorization": f"Bearer {access_token}"},
            params={"per_page": _REPOSITORY_PAGE_SIZE, "page": page},
            timeout=10,
        )
        if response.status_code != 200:
            logger.warning(
                "github_grant.list_repositories_failed",
                status_code=response.status_code,
                installation_id=installation_id,
            )
            raise requests.RequestException(
                f"Unexpected status {response.status_code} listing installation repositories"
            )
        raw_repositories = response.json().get("repositories", [])
        if not isinstance(raw_repositories, list):
            break
        for repository in raw_repositories:
            if not isinstance(repository, dict) or not repository.get("full_name"):
                continue
            repositories.append(
                {
                    "installation_id": installation_id,
                    "full_name": repository["full_name"],
                    "default_branch": repository.get("default_branch"),
                    "private": repository.get("private"),
                }
            )
        if len(raw_repositories) < _REPOSITORY_PAGE_SIZE:
            break
    return repositories
