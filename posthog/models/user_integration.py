import time
from datetime import datetime
from typing import TYPE_CHECKING, Any

from django.conf import settings
from django.db import models

if TYPE_CHECKING:
    from posthog.models.integration import GitHubInstallationAccess, GitHubUserAuthorization
    from posthog.models.user import User

import requests
import structlog

from posthog.helpers.encrypted_fields import EncryptedJSONField
from posthog.models.github_integration_base import GitHubIntegrationBase
from posthog.models.utils import UUIDModel

logger = structlog.get_logger(__name__)


# GitHub rejects a refresh token with one of these error codes when it's no longer valid and the user can remediate this
# We then force the user to re-authorize through the install flow, by deleting the bad integration
_GITHUB_UNRECOVERABLE_REFRESH_ERRORS = {
    "bad_refresh_token",
    "refresh_token_expired",
    "unauthorized_client",
}


class UserIntegration(UUIDModel):
    """User-scoped integration with an external service.

    Contents for GitHub:
    - `integration_id` holds the GitHub App installation_id
    - `config` holds installation metadata + user identity (login, id)
    - `sensitive_config` holds installation access token + user-to-server tokens
    """

    class IntegrationKind(models.TextChoices):
        GITHUB = "github"

    user = models.ForeignKey(
        "posthog.User",
        on_delete=models.CASCADE,
        related_name="integrations",
    )
    kind = models.CharField(max_length=32, choices=IntegrationKind.choices)
    # The ID of the integration in the external system, same as on Integration
    integration_id = models.TextField()
    config = models.JSONField(default=dict)
    sensitive_config = EncryptedJSONField(default=dict)
    repository_cache = models.JSONField(default=list, blank=True)
    repository_cache_updated_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "posthog_user_integration"
        unique_together = [("user", "kind", "integration_id")]


class ReauthorizationRequired(Exception):
    """The stored GitHub tokens cannot produce a usable access token; user must re-authorize."""


class UserGitHubIntegration(GitHubIntegrationBase):
    """Helper for operating on a GitHub `UserIntegration`.

    Manages two token types:
    - Installation access token (sensitive_config["access_token"]):
      app-level token for repo operations (listing repos, checking access).
      Refreshed via the GitHub App JWT, same as team-level `GitHubIntegration`.
    - User-to-server token (sensitive_config["user_access_token"]):
      acts as the user in repos covered by the installation. Used for creating PRs, commits, etc.
        Refreshed via the OAuth refresh-token flow.

    `config` layout:

        {
            "installation_id": "12345",
            "expires_in": 3600,              # installation token TTL
            "refreshed_at": <unix>,          # installation token refresh time
            "repository_selection": "selected",
            "account": {"type": "User", "name": "octocat"},
            "github_user": {"login": "octocat", "id": 123},
            "user_token_refreshed_at": <unix>,
            "user_access_token_expires_at": <unix>,
            "user_refresh_token_expires_at": <unix>,
        }

    `sensitive_config` layout:

        {
            "access_token": "<installation token>",
            "user_access_token": "<user-to-server token>",
            "user_refresh_token": "<user-to-server refresh token>",
        }
    """

    integration: UserIntegration

    def __init__(self, integration: UserIntegration) -> None:
        if integration.kind != "github":
            raise Exception("UserGitHubIntegration initialized with non-github integration")
        self.integration = integration

    # --- Token refresh hooks ---

    def _on_token_refresh_failed(self, response: requests.Response) -> None:
        logger.warning(
            "UserGitHubIntegration: installation token refresh failed",
            user_id=self.integration.user_id,
            status_code=response.status_code,
        )

    def _on_token_refreshed(self) -> None:
        logger.info(
            "UserGitHubIntegration: refreshed installation access token",
            user_id=self.integration.user_id,
        )

    # --- Identity ---

    @property
    def github_login(self) -> str | None:
        github_user = self.integration.config.get("github_user")
        if isinstance(github_user, dict):
            login = github_user.get("login")
            return str(login) if login else None
        return None

    @property
    def github_id(self) -> int | None:
        github_user = self.integration.config.get("github_user")
        if isinstance(github_user, dict):
            gh_id = github_user.get("id")
            return int(gh_id) if gh_id is not None else None
        return None

    # --- User-to-server token ---

    @property
    def user_access_token(self) -> str | None:
        return self.integration.sensitive_config.get("user_access_token") if self.integration.sensitive_config else None

    @property
    def user_refresh_token(self) -> str | None:
        return (
            self.integration.sensitive_config.get("user_refresh_token") if self.integration.sensitive_config else None
        )

    def user_access_token_expired(self) -> bool:
        expires_at = self.integration.config.get("user_access_token_expires_at")
        if not expires_at:
            return False
        refreshed_at = self.integration.config.get("user_token_refreshed_at") or self.integration.created_at.timestamp()
        threshold = max(1, int((expires_at - refreshed_at) // 2))
        return time.time() > expires_at - threshold

    def user_refresh_token_expired(self) -> bool:
        expires_at = self.integration.config.get("user_refresh_token_expires_at")
        if not expires_at:
            return False
        return time.time() > expires_at

    def refresh_user_access_token(self) -> None:
        """Exchange the refresh token for a fresh user-to-server access token.

        Deletes the integration row and raises :class:`ReauthorizationRequired`
        when GitHub signals the refresh token can't produce a new access token.
        """
        client_id = settings.GITHUB_APP_CLIENT_ID
        client_secret = settings.GITHUB_APP_CLIENT_SECRET
        refresh_token = self.user_refresh_token
        if not client_id or not client_secret:
            raise Exception("GITHUB_APP_CLIENT_ID / GITHUB_APP_CLIENT_SECRET not configured, cannot refresh user token")
        if not refresh_token:
            self._discard("no user refresh token stored")
            raise ReauthorizationRequired("No refresh token stored for this GitHub integration.")

        response = requests.post(
            "https://github.com/login/oauth/access_token",
            json={
                "client_id": client_id,
                "client_secret": client_secret,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
            headers={"Accept": "application/json"},
            timeout=10,
        )
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        access_token = payload.get("access_token")
        if not access_token:
            error = payload.get("error")
            if error in _GITHUB_UNRECOVERABLE_REFRESH_ERRORS:
                self._discard(f"refresh rejected by GitHub: {error}")
                raise ReauthorizationRequired(f"GitHub refused the stored refresh token ({error}).")
            raise Exception(f"Unexpected refresh failure from GitHub: {error or response.status_code}")

        self._apply_user_token_payload(payload)

    def get_usable_user_access_token(self) -> str:
        """Return a non-expired user-to-server access token, refreshing on demand.

        Raises :class:`ReauthorizationRequired` if the row lacks tokens, the
        refresh token is expired, or GitHub rejects a refresh attempt.
        """
        if not self.user_access_token:
            self._discard("no user access token stored")
            raise ReauthorizationRequired("No user access token stored for this GitHub integration.")
        if self.user_refresh_token_expired():
            self._discard("user refresh token expired")
            raise ReauthorizationRequired("The stored GitHub user refresh token has expired.")
        if self.user_access_token_expired():
            self.refresh_user_access_token()
        token = self.user_access_token
        assert token is not None, "user_access_token cleared unexpectedly after refresh"
        return token

    def _apply_user_token_payload(self, payload: dict[str, Any]) -> None:
        """Write a fresh user token pair + expirations onto the integration row."""
        now = int(time.time())
        access_token = payload.get("access_token")
        refresh_token = payload.get("refresh_token") or self.user_refresh_token
        access_expires_in = payload.get("expires_in")
        refresh_expires_in = payload.get("refresh_token_expires_in")

        self.integration.sensitive_config = {
            **(self.integration.sensitive_config or {}),
            "user_access_token": access_token,
            "user_refresh_token": refresh_token,
        }
        config = dict(self.integration.config or {})
        config["user_token_refreshed_at"] = now
        # When GitHub disables user-token expiration, refresh responses omit expiry fields.
        # Clear stored expiries so we do not treat a non-expiring token as perpetually expired.
        if access_expires_in is not None:
            config["user_access_token_expires_at"] = now + int(access_expires_in)
        else:
            config.pop("user_access_token_expires_at", None)
        if refresh_expires_in is not None:
            config["user_refresh_token_expires_at"] = now + int(refresh_expires_in)
        else:
            config.pop("user_refresh_token_expires_at", None)
        self.integration.config = config
        self.integration.save(update_fields=["sensitive_config", "config", "updated_at"])

    def _discard(self, reason: str) -> None:
        """Delete the integration when stored credentials are unusable.

        Deletion keeps the invariant that every integration row carries working tokens.
        The user falls back to the Connect flow.
        """
        logger.info("UserGitHubIntegration: discarding integration", user_id=self.integration.user_id, reason=reason)
        try:
            self.integration.delete()
        except Exception:
            logger.warning("UserGitHubIntegration: failed to delete unusable integration", exc_info=True)


def user_github_integration_from_installation(
    user: "User",
    installation: "GitHubInstallationAccess",
    authorization: "GitHubUserAuthorization",
) -> UserIntegration:
    """Create or update the user-scoped GitHub integration for an installation + authorization pair.

    Uses ``update_or_create`` keyed on ``(user, kind, integration_id)`` so that
    re-authorizing the same installation refreshes the stored tokens rather than
    creating a duplicate row.
    """
    from posthog.models.integration import dot_get

    now = int(time.time())
    try:
        expires_in = datetime.fromisoformat(installation.token_expires_at).timestamp() - now
    except (ValueError, AttributeError):
        expires_in = 3600

    config: dict[str, Any] = {
        "installation_id": installation.installation_id,
        "expires_in": expires_in,
        "refreshed_at": now,
        "repository_selection": installation.repository_selection,
        "account": {
            "type": dot_get(installation.installation_info, "account.type", None),
            "name": dot_get(installation.installation_info, "account.login", installation.installation_id),
        },
        "github_user": {
            "login": authorization.gh_login,
            "id": authorization.gh_id,
        },
        "user_token_refreshed_at": now,
    }
    if authorization.access_token_expires_in is not None:
        config["user_access_token_expires_at"] = now + authorization.access_token_expires_in
    if authorization.refresh_token_expires_in is not None:
        config["user_refresh_token_expires_at"] = now + authorization.refresh_token_expires_in

    sensitive_config = {
        "access_token": installation.access_token,
        "user_access_token": authorization.access_token,
        "user_refresh_token": authorization.refresh_token,
    }

    integration, _ = UserIntegration.objects.update_or_create(
        user=user,
        kind=UserIntegration.IntegrationKind.GITHUB,
        integration_id=installation.installation_id,
        defaults={
            "config": config,
            "sensitive_config": sensitive_config,
        },
    )
    return integration
