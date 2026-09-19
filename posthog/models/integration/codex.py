"""ChatGPT plan credentials for Codex cloud tasks.

The user logs in once on their own machine with the Codex CLI. Desktop submits the `auth.json` that
the login wrote. From then on this module owns the refresh chain: it stores the tokens on the user's
`UserIntegration` row (kind=codex), refreshes the short-lived access token with the single-use refresh
token, and hands a short-lived access token to each cloud run. No route ever returns the refresh token.
"""

import json
import base64
from dataclasses import field
from datetime import UTC, datetime, timedelta
from typing import Any

from django.db import models, transaction
from django.utils import timezone

import requests
import structlog

from posthog.dataclasses import frozen
from posthog.egress.openai_auth import OPENAI_OAUTH_REVOKE_URL, OPENAI_OAUTH_TOKEN_URL, openai_auth_request
from posthog.exceptions_capture import capture_exception
from posthog.models.user_integration import UserIntegration

logger = structlog.get_logger(__name__)

# The public OAuth client id of the Codex CLI. The tokens Desktop submits were issued to it, so refresh
# and revoke must name it too.
CODEX_OAUTH_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
CODEX_OAUTH_SCOPE = "openid profile email"
OPENAI_AUTH_TIMEOUT_SECONDS = 15.0
# Refresh a little before the token expires so a run never starts with a token about to die.
ACCESS_TOKEN_REFRESH_MARGIN = timedelta(minutes=5)
# A forced refresh right after another refresh means a second run saw the 401 for the same old
# token. Give it the fresh token instead of burning another refresh.
FORCED_REFRESH_DEDUPE_WINDOW = timedelta(seconds=30)
# Codex access tokens carry `exp`; this is only the fallback when a token has none.
DEFAULT_ACCESS_TOKEN_LIFETIME = timedelta(hours=1)

CODEX_AUTH_CLAIM = "https://api.openai.com/auth"
CODEX_PROFILE_CLAIM = "https://api.openai.com/profile"


class CodexIntegrationStatus(models.TextChoices):
    CONNECTED = "connected"
    REAUTH_REQUIRED = "reauth_required"
    NOT_CONNECTED = "not_connected"


STATUS_CONNECTED = CodexIntegrationStatus.CONNECTED.value
STATUS_REAUTH_REQUIRED = CodexIntegrationStatus.REAUTH_REQUIRED.value
STATUS_NOT_CONNECTED = CodexIntegrationStatus.NOT_CONNECTED.value


class CodexAuthError(Exception):
    """The submitted credential is not usable, or OpenAI could not be reached."""


class CodexReauthRequired(CodexAuthError):
    """The refresh chain is dead. The user must log in again and reconnect."""


class CodexNotConnected(CodexReauthRequired):
    """The user has no connected ChatGPT account."""


@frozen
class CodexTokens:
    access_token: str = field(repr=False)
    refresh_token: str = field(repr=False)
    id_token: str | None = field(repr=False)
    account_id: str
    plan_type: str | None
    email: str | None
    expires_at: datetime


@frozen
class CodexAccessGrant:
    """What a cloud run gets: enough to sign in the Codex app-server, and nothing that lasts."""

    access_token: str = field(repr=False)
    account_id: str
    plan_type: str | None
    expires_at: datetime


def decode_jwt_claims(token: str) -> dict[str, Any]:
    """Read the claims of a JWT without checking its signature. OpenAI verifies the token; we only read ids."""
    parts = token.split(".")
    if len(parts) != 3:
        raise CodexAuthError("The access token is not a JWT.")
    payload = parts[1]
    try:
        raw = base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
        claims = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as error:
        raise CodexAuthError("The access token claims could not be decoded.") from error
    if not isinstance(claims, dict):
        raise CodexAuthError("The access token claims are not an object.")
    return claims


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _tokens_from_parts(access_token: str, refresh_token: str, id_token: str | None) -> CodexTokens:
    claims = decode_jwt_claims(access_token)
    auth_claims = claims.get(CODEX_AUTH_CLAIM)
    if not isinstance(auth_claims, dict):
        auth_claims = {}
    account_id = _optional_str(auth_claims.get("chatgpt_account_id"))
    if account_id is None:
        raise CodexAuthError("The access token has no ChatGPT account id.")
    exp = claims.get("exp")
    if isinstance(exp, int | float) and not isinstance(exp, bool):
        expires_at = datetime.fromtimestamp(exp, tz=UTC)
    else:
        expires_at = timezone.now() + DEFAULT_ACCESS_TOKEN_LIFETIME

    email = None
    if id_token:
        try:
            email = _optional_str(decode_jwt_claims(id_token).get("email"))
        except CodexAuthError:
            id_token = None
    if email is None:
        profile = claims.get(CODEX_PROFILE_CLAIM)
        if isinstance(profile, dict):
            email = _optional_str(profile.get("email"))

    return CodexTokens(
        access_token=access_token,
        refresh_token=refresh_token,
        id_token=id_token,
        account_id=account_id,
        plan_type=_optional_str(auth_claims.get("chatgpt_plan_type")),
        email=email,
        expires_at=expires_at,
    )


def parse_codex_auth_json(raw: object) -> CodexTokens:
    """Read the `auth.json` that `codex login` writes: `{"tokens": {"access_token", "refresh_token", "id_token", ...}}`."""
    if not isinstance(raw, dict):
        raise CodexAuthError("The auth file is not a JSON object.")
    tokens = raw.get("tokens")
    if not isinstance(tokens, dict):
        raise CodexAuthError("The auth file has no tokens. Log in with ChatGPT, not with an API key.")
    access_token = _optional_str(tokens.get("access_token"))
    refresh_token = _optional_str(tokens.get("refresh_token"))
    if access_token is None or refresh_token is None:
        raise CodexAuthError("The auth file has no access token or no refresh token.")
    return _tokens_from_parts(access_token, refresh_token, _optional_str(tokens.get("id_token")))


def _refresh_failure_code(response: requests.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return f"http_{response.status_code}"
    error = body.get("error") if isinstance(body, dict) else None
    if isinstance(error, dict):
        return _optional_str(error.get("code")) or _optional_str(error.get("type")) or f"http_{response.status_code}"
    return _optional_str(error) or f"http_{response.status_code}"


def refresh_codex_tokens(refresh_token: str, *, source: str) -> CodexTokens:
    """Exchange the single-use refresh token for a new token set. A 4xx means the chain is dead."""
    try:
        response = openai_auth_request(
            "POST",
            OPENAI_OAUTH_TOKEN_URL,
            source=source,
            endpoint="oauth/token",
            timeout=OPENAI_AUTH_TIMEOUT_SECONDS,
            json={
                "client_id": CODEX_OAUTH_CLIENT_ID,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "scope": CODEX_OAUTH_SCOPE,
            },
        )
    except requests.RequestException as error:
        raise CodexAuthError("Could not reach OpenAI to refresh the ChatGPT token.") from error
    if 400 <= response.status_code < 500:
        code = _refresh_failure_code(response)
        raise CodexReauthRequired(f"OpenAI rejected the refresh token ({code}).")
    if not response.ok:
        raise CodexAuthError(f"OpenAI returned {response.status_code} on refresh.")
    try:
        body = response.json()
    except ValueError as error:
        raise CodexAuthError("OpenAI returned a refresh response that is not JSON.") from error
    access_token = _optional_str(body.get("access_token")) if isinstance(body, dict) else None
    if access_token is None:
        raise CodexAuthError("OpenAI returned no access token on refresh.")
    # OpenAI rotates the refresh token on every use; keep the old one only when the response has none.
    new_refresh_token = _optional_str(body.get("refresh_token")) or refresh_token
    return _tokens_from_parts(access_token, new_refresh_token, _optional_str(body.get("id_token")))


def revoke_codex_refresh_token(refresh_token: str, *, source: str) -> None:
    """Best effort: end the device authorization the user made for PostHog. A failure is logged, not raised."""
    try:
        response = openai_auth_request(
            "POST",
            OPENAI_OAUTH_REVOKE_URL,
            source=source,
            endpoint="oauth/revoke",
            timeout=OPENAI_AUTH_TIMEOUT_SECONDS,
            data={"token": refresh_token, "token_type_hint": "refresh_token", "client_id": CODEX_OAUTH_CLIENT_ID},
        )
    except requests.RequestException as error:
        logger.warning("codex_refresh_token_revoke_failed", error=str(error))
        return
    if not response.ok:
        logger.warning("codex_refresh_token_revoke_rejected", status_code=response.status_code)


class CodexUserIntegration:
    """The one `UserIntegration` row of kind=codex for a user."""

    KIND = UserIntegration.IntegrationKind.CODEX

    def __init__(self, integration: UserIntegration) -> None:
        self.integration = integration

    @classmethod
    def for_user(cls, user_id: int) -> "CodexUserIntegration | None":
        row = UserIntegration.objects.filter(user_id=user_id, kind=cls.KIND).first()
        return cls(row) if row is not None else None

    @classmethod
    def connect(cls, user_id: int, tokens: CodexTokens, *, source: str) -> "CodexUserIntegration":
        """Store a submitted token set after one refresh.

        The refresh proves the chain is live, and it makes the server the current holder: the tokens
        in the file on the user's machine stop working by construction, whatever the client does.
        """
        fresh = refresh_codex_tokens(tokens.refresh_token, source=source)
        now = timezone.now()
        with transaction.atomic():
            UserIntegration.objects.filter(user_id=user_id, kind=cls.KIND).exclude(
                integration_id=fresh.account_id
            ).delete()
            row, _ = UserIntegration.objects.update_or_create(
                user_id=user_id,
                kind=cls.KIND,
                integration_id=fresh.account_id,
                defaults={
                    "config": {
                        "plan_type": fresh.plan_type,
                        "email": fresh.email,
                        "status": STATUS_CONNECTED,
                        "connected_at": now.isoformat(),
                        "last_refreshed_at": now.isoformat(),
                    },
                    "sensitive_config": cls._sensitive_config(fresh),
                },
            )
        return cls(row)

    @classmethod
    def issue_access_grant(cls, user_id: int, *, force: bool, source: str) -> CodexAccessGrant:
        """The access token for a cloud run, refreshed under a row lock when expired or forced.

        The refresh token is single use, so two runs of one user must not refresh at the same time.
        The row lock makes the second wait, and the dedupe window hands it the token the first stored.
        """
        reauth_error: CodexReauthRequired | None = None
        with transaction.atomic():
            row = UserIntegration.objects.select_for_update().filter(user_id=user_id, kind=cls.KIND).first()
            if row is None:
                raise CodexNotConnected("No ChatGPT account is connected.")
            integration = cls(row)
            if integration.status != STATUS_CONNECTED:
                raise CodexReauthRequired("The ChatGPT account must be reconnected.")
            if integration._needs_refresh(force):
                try:
                    integration._refresh(source=source)
                except CodexReauthRequired as error:
                    integration._mark_reauth_required(str(error))
                    reauth_error = error
        if reauth_error is not None:
            raise reauth_error
        return integration.access_grant()

    @property
    def status(self) -> str:
        return str(self.integration.config.get("status") or STATUS_REAUTH_REQUIRED)

    @property
    def plan_type(self) -> str | None:
        return _optional_str(self.integration.config.get("plan_type"))

    @property
    def email(self) -> str | None:
        return _optional_str(self.integration.config.get("email"))

    @property
    def connected_at(self) -> str | None:
        return _optional_str(self.integration.config.get("connected_at"))

    @property
    def account_id(self) -> str:
        return self.integration.integration_id

    def is_connected(self) -> bool:
        return self.status == STATUS_CONNECTED

    def access_grant(self) -> CodexAccessGrant:
        access_token = _optional_str(self.integration.sensitive_config.get("access_token"))
        if access_token is None:
            raise CodexReauthRequired("The ChatGPT account must be reconnected.")
        return CodexAccessGrant(
            access_token=access_token,
            account_id=self.account_id,
            plan_type=self.plan_type,
            expires_at=self._expires_at() or timezone.now(),
        )

    def access_token_expired(self, now: datetime | None = None) -> bool:
        expires_at = self._expires_at()
        if expires_at is None:
            return True
        return (now or timezone.now()) + ACCESS_TOKEN_REFRESH_MARGIN >= expires_at

    def disconnect(self, *, source: str) -> None:
        refresh_token = _optional_str(self.integration.sensitive_config.get("refresh_token"))
        if refresh_token is not None:
            revoke_codex_refresh_token(refresh_token, source=source)
        self.integration.delete()

    def _needs_refresh(self, force: bool) -> bool:
        if force:
            last_refreshed_at = self._parse_datetime(self.integration.config.get("last_refreshed_at"))
            recently_refreshed = (
                last_refreshed_at is not None and timezone.now() - last_refreshed_at < FORCED_REFRESH_DEDUPE_WINDOW
            )
            return not recently_refreshed or self.access_token_expired()
        return self.access_token_expired()

    def _refresh(self, *, source: str) -> None:
        refresh_token = _optional_str(self.integration.sensitive_config.get("refresh_token"))
        if refresh_token is None:
            raise CodexReauthRequired("The ChatGPT account has no refresh token.")
        try:
            fresh = refresh_codex_tokens(refresh_token, source=source)
        except CodexAuthError as error:
            if not isinstance(error, CodexReauthRequired):
                capture_exception(error)
            raise
        self.integration.sensitive_config = self._sensitive_config(fresh)
        self.integration.config = {
            **self.integration.config,
            "plan_type": fresh.plan_type or self.plan_type,
            "email": fresh.email or self.email,
            "last_refreshed_at": timezone.now().isoformat(),
        }
        self.integration.save(update_fields=["config", "sensitive_config"])

    def _mark_reauth_required(self, reason: str) -> None:
        # Drop the dead chain so nothing can retry it; keep the row so settings can show "Reconnect".
        self.integration.sensitive_config = {}
        self.integration.config = {
            **self.integration.config,
            "status": STATUS_REAUTH_REQUIRED,
            "reauth_reason": reason,
        }
        self.integration.save(update_fields=["config", "sensitive_config"])
        logger.warning("codex_subscription_reauth_required", user_id=self.integration.user_id, reason=reason)

    def _expires_at(self) -> datetime | None:
        return self._parse_datetime(self.integration.sensitive_config.get("access_token_expires_at"))

    @staticmethod
    def _parse_datetime(value: object) -> datetime | None:
        if not isinstance(value, str):
            return None
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None

    @staticmethod
    def _sensitive_config(tokens: CodexTokens) -> dict[str, Any]:
        return {
            "access_token": tokens.access_token,
            "refresh_token": tokens.refresh_token,
            "id_token": tokens.id_token,
            "access_token_expires_at": tokens.expires_at.isoformat(),
        }
