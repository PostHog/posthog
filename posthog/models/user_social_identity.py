import time
from typing import TYPE_CHECKING, Any

from django.conf import settings
from django.db import models

import requests
import structlog

from posthog.helpers.encrypted_fields import EncryptedJSONField
from posthog.models.organization_domain import OrganizationDomain
from posthog.models.utils import UUIDModel
from posthog.utils import get_instance_available_sso_providers

logger = structlog.get_logger(__name__)

if TYPE_CHECKING:
    from posthog.models.user import User


GITHUB_PROVIDER = "github"
# Providers whose rows the user can remove; SAML is managed by the IdP side.
_DISCONNECTABLE_PROVIDERS = {"github", "google-oauth2", "gitlab"}

# GitHub rejects a refresh token with one of these error codes when it's
# no longer valid; the user must re-authorize through the link flow.
_GITHUB_UNRECOVERABLE_REFRESH_ERRORS = frozenset(
    {
        "bad_refresh_token",
        "incorrect_client_credentials",
        "refresh_token_expired",
        "unauthorized_client",
    }
)


class UserSocialIdentity(UUIDModel):
    """Identity-only link between a PostHog user and a third-party account.

    Decoupled from ``UserSocialAuth`` (python-social-auth) which controls *login*.
    A user with login enabled has both a ``UserSocialAuth`` row and a
    ``UserSocialIdentity`` row. Identity-only users have only the latter.

    For backward compatibility, a ``UserSocialAuth`` row without a matching
    ``UserSocialIdentity`` is treated as if the identity exists. The identity
    row is backfilled lazily when the user toggles off login.

    Unlike ``UserSocialAuth`` (unique on provider+uid), multiple PostHog users
    may hold a ``UserSocialIdentity`` for the same provider+uid — that's
    intentional so several team members can map to the same external identity
    for attribution purposes.
    """

    user = models.ForeignKey(
        "posthog.User",
        on_delete=models.CASCADE,
        related_name="social_identities",
    )
    provider = models.CharField(max_length=32)
    uid = models.CharField(max_length=255)
    extra_data = models.JSONField(default=dict)
    sensitive_config = EncryptedJSONField(default=dict, ignore_decrypt_errors=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "posthog_user_social_identity"
        unique_together = [("user", "provider")]

    @property
    def access_token(self) -> str | None:
        return self.sensitive_config.get("access_token") if self.sensitive_config else None

    @property
    def refresh_token(self) -> str | None:
        return self.sensitive_config.get("refresh_token") if self.sensitive_config else None


def sso_enforcement_for(user: "User") -> str | None:
    if not user.email:
        return None
    return OrganizationDomain.objects.get_sso_enforcement_for_email_address(user.email)


def can_user_enable_login_for(user: "User", provider: str) -> bool:
    """Whether the Settings UI toggle should be clickable for this (user, provider).

    SSO enforcement blocks enabling login for any provider other than the enforced one.
    """
    enforcement = sso_enforcement_for(user)
    return enforcement is None or enforcement == provider


def available_providers_for_user(user: "User") -> list[str]:
    """Ordered list of providers to show in the user's Linked accounts section.

    When SSO is enforced, the enforced provider is always shown. GitHub is also
    always included when available, because its link flow bypasses social-auth
    entirely and can be used for identity-only linking regardless of SSO policy.
    """
    enforcement = sso_enforcement_for(user)
    if enforcement is not None:
        providers = [enforcement]
        if enforcement != GITHUB_PROVIDER:
            all_available = get_instance_available_sso_providers()
            if all_available.get(GITHUB_PROVIDER):
                providers.append(GITHUB_PROVIDER)
        return providers
    return [name for name, available in get_instance_available_sso_providers().items() if available]


def can_disconnect_provider(user: "User", provider: str) -> bool:
    """Whether the given provider can be disconnected by the user.

    Disallowed when:
    - the provider is the enforced SSO method, or
    - the provider isn't one whose row users manage directly (e.g. SAML, managed by IdP).
    """
    if provider not in _DISCONNECTABLE_PROVIDERS:
        return False
    return sso_enforcement_for(user) != provider


class ReauthorizationRequired(Exception):
    """The stored GitHub tokens cannot produce a usable access token; user must re-authorize."""


class UserGitHubIntegration:
    """Helper for operating on a GitHub ``UserSocialIdentity`` row's tokens.

    Mirrors :class:`GitHubIntegration` but for the user-to-server tokens stored
    per-user. The identity row's ``sensitive_config`` carries
    ``{"access_token", "refresh_token"}``; ``extra_data`` carries
    ``access_token_expires_at`` / ``refresh_token_expires_at`` / ``refreshed_at``
    as unix timestamps alongside the identifying ``login`` / ``id`` fields.
    """

    identity: UserSocialIdentity

    def __init__(self, identity: UserSocialIdentity) -> None:
        if identity.provider != GITHUB_PROVIDER:
            raise Exception("UserGitHubIntegration initialized with non-github identity")
        self.identity = identity

    @property
    def access_token(self) -> str | None:
        return self.identity.access_token

    @property
    def refresh_token(self) -> str | None:
        return self.identity.refresh_token

    def access_token_expired(self, threshold: int | None = None) -> bool:
        """Half-TTL check, mirroring :meth:`GitHubIntegration.access_token_expired`."""
        expires_at = self.identity.extra_data.get("access_token_expires_at") if self.identity.extra_data else None
        if not expires_at:
            return False
        # Refresh once we're halfway through the remaining lifetime so short blips don't
        # trip an expired call that races the refresh.
        refreshed_at = self.identity.extra_data.get("refreshed_at") or self.identity.created_at.timestamp()
        if threshold is None:
            threshold = max(1, int((expires_at - refreshed_at) // 2))
        return time.time() > expires_at - threshold

    def refresh_token_expired(self) -> bool:
        expires_at = self.identity.extra_data.get("refresh_token_expires_at") if self.identity.extra_data else None
        if not expires_at:
            return False
        return time.time() > expires_at

    def refresh_access_token(self) -> None:
        """Exchange the refresh token for a fresh access token.

        Deletes the identity row and raises :class:`ReauthorizationRequired`
        when GitHub signals the refresh token can't produce a new access token.
        """
        client_id = settings.GITHUB_APP_OAUTH_CLIENT_ID
        client_secret = settings.GITHUB_APP_OAUTH_CLIENT_SECRET
        refresh_token = self.refresh_token
        if not client_id or not client_secret:
            raise Exception("GITHUB_APP_OAUTH_CLIENT_ID/SECRET not configured, cannot refresh user token")
        if not refresh_token:
            self._discard("no refresh token stored")
            raise ReauthorizationRequired("No refresh token stored for this GitHub identity.")

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

        self._apply_token_payload(payload)

    def get_usable_access_token(self) -> str:
        """Return a non-expired access token, refreshing on demand.

        Raises :class:`ReauthorizationRequired` if the row lacks tokens, the
        refresh token is expired, or GitHub rejects a refresh attempt.
        """
        if not self.access_token:
            self._discard("no access token stored")
            raise ReauthorizationRequired("No access token stored for this GitHub identity.")
        if self.refresh_token_expired():
            self._discard("refresh token expired")
            raise ReauthorizationRequired("The stored GitHub refresh token has expired.")
        if self.access_token_expired():
            self.refresh_access_token()
        access_token = self.access_token
        assert access_token is not None, "access_token cleared unexpectedly after refresh"
        return access_token

    def _apply_token_payload(self, payload: dict[str, Any]) -> None:
        """Write a fresh token pair + expirations onto the identity row."""
        now = int(time.time())
        access_token = payload.get("access_token")
        refresh_token = payload.get("refresh_token") or self.refresh_token
        access_expires_in = payload.get("expires_in")
        refresh_expires_in = payload.get("refresh_token_expires_in")

        self.identity.sensitive_config = {
            **(self.identity.sensitive_config or {}),
            "access_token": access_token,
            "refresh_token": refresh_token,
        }
        extra = dict(self.identity.extra_data or {})
        extra["refreshed_at"] = now
        if access_expires_in is not None:
            extra["access_token_expires_at"] = now + int(access_expires_in)
        if refresh_expires_in is not None:
            extra["refresh_token_expires_at"] = now + int(refresh_expires_in)
        self.identity.extra_data = extra
        self.identity.save(update_fields=["sensitive_config", "extra_data", "updated_at"])

    def _discard(self, reason: str) -> None:
        """Delete the identity row when stored credentials are unusable.

        Deletion keeps the "every GitHub identity row carries working tokens"
        invariant intact; the user falls back to the Connect flow.
        """
        logger.info("UserGitHubIntegration: discarding identity", user_id=self.identity.user_id, reason=reason)
        try:
            self.identity.delete()
        except Exception:
            logger.warning("UserGitHubIntegration: failed to delete unusable identity", exc_info=True)


def apply_github_authorization(
    identity: UserSocialIdentity,
    *,
    gh_id: int,
    gh_login: str,
    access_token: str,
    refresh_token: str | None,
    access_token_expires_in: int | None,
    refresh_token_expires_in: int | None,
) -> None:
    """Persist a fresh GitHub App user authorization onto the identity row.

    Used on first link and on re-link (when the user re-authorizes). Writes
    identity + credential fields in one ``save`` so the row only ever exists
    with a working pair.
    """
    now = int(time.time())
    extra = dict(identity.extra_data or {})
    extra["login"] = gh_login
    extra["id"] = gh_id
    extra["refreshed_at"] = now
    if access_token_expires_in is not None:
        extra["access_token_expires_at"] = now + access_token_expires_in
    if refresh_token_expires_in is not None:
        extra["refresh_token_expires_at"] = now + refresh_token_expires_in
    identity.extra_data = extra
    identity.sensitive_config = {
        **(identity.sensitive_config or {}),
        "access_token": access_token,
        "refresh_token": refresh_token,
    }
    identity.save()
