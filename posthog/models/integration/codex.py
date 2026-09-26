"""ChatGPT plan credentials for Codex cloud tasks.

The user logs in once on their own machine with the Codex CLI. Desktop submits the `auth.json` that
the login wrote. From then on this module owns the refresh chain: it stores the tokens on the user's
`UserIntegration` row (kind=codex), refreshes the access token with the single-use refresh token, and
hands the access token to each cloud run. An access token can stay valid for several days, so a run can
keep it after the run ends. No route ever returns the refresh token.
"""

import json
import base64
import hashlib
from dataclasses import field
from datetime import UTC, datetime, timedelta
from typing import Any

from django.db import connection, models, transaction
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
# Codex access tokens carry `exp`; this is only the fallback when a token has none or one out of range.
DEFAULT_ACCESS_TOKEN_LIFETIME = timedelta(hours=1)
# OpenAI answers a rate-limited or timed-out refresh with these; the chain is still alive.
TRANSIENT_REFRESH_STATUS_CODES = frozenset({408, 425, 429})

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


@frozen
class CodexTokens:
    access_token: str = field(repr=False)
    refresh_token: str = field(repr=False)
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
    refreshed: bool


def access_token_fingerprint(access_token: str) -> str:
    """The SHA-256 hex digest a run sends back to name the token Codex rejected, so the token itself never travels twice."""
    return hashlib.sha256(access_token.encode()).hexdigest()


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
    expires_at = timezone.now() + DEFAULT_ACCESS_TOKEN_LIFETIME
    exp = claims.get("exp")
    if isinstance(exp, int | float) and not isinstance(exp, bool):
        try:
            expires_at = datetime.fromtimestamp(exp, tz=UTC)
        except (OverflowError, OSError, ValueError):
            pass

    email = None
    if id_token:
        try:
            email = _optional_str(decode_jwt_claims(id_token).get("email"))
        except CodexAuthError:
            pass
    if email is None:
        profile = claims.get(CODEX_PROFILE_CLAIM)
        if isinstance(profile, dict):
            email = _optional_str(profile.get("email"))

    return CodexTokens(
        access_token=access_token,
        refresh_token=refresh_token,
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
    """Exchange the single-use refresh token for a new token set.

    A 4xx means the chain is dead, except the codes OpenAI uses for throttling and timeouts.
    """
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
    if response.status_code in TRANSIENT_REFRESH_STATUS_CODES:
        raise CodexAuthError(f"OpenAI returned {response.status_code} on refresh.")
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
            json={"token": refresh_token, "token_type_hint": "refresh_token", "client_id": CODEX_OAUTH_CLIENT_ID},
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
    def _lock_user(cls, user_id: int) -> None:
        # Row locks cannot protect the first connection because its record does not exist yet.
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s, hashtext(%s))", [user_id, "user_integration:codex"])

    @classmethod
    def connect(cls, user_id: int, tokens: CodexTokens, *, source: str) -> "CodexUserIntegration":
        """Store a submitted token set after one refresh.

        The refresh proves the chain is live, and it makes the server the current holder: the tokens
        in the file on the user's machine stop working by construction, whatever the client does.
        """
        with transaction.atomic():
            cls._lock_user(user_id)
            fresh = refresh_codex_tokens(tokens.refresh_token, source=source)
            now = timezone.now()
            row, _ = UserIntegration.objects.update_or_create(
                user_id=user_id,
                kind=cls.KIND,
                defaults={
                    "integration_id": fresh.account_id,
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
    def issue_access_grant(
        cls, user_id: int, *, rejected_access_token_sha256: str | None, source: str
    ) -> CodexAccessGrant:
        """The access token for a cloud run, refreshed under a row lock when expired or rejected.

        The refresh token is single use, so two runs of one user must not refresh at the same time.
        The row lock makes the second wait. A run that reports a rejected token names it by digest,
        so a token the first run already replaced is handed over as is instead of refreshed again.
        """
        reauth_error: CodexReauthRequired | None = None
        refreshed = False
        with transaction.atomic():
            cls._lock_user(user_id)
            row = UserIntegration.objects.select_for_update().filter(user_id=user_id, kind=cls.KIND).first()
            if row is None:
                raise CodexReauthRequired("No ChatGPT account is connected.")
            integration = cls(row)
            if integration.status != STATUS_CONNECTED:
                raise CodexReauthRequired("The ChatGPT account must be reconnected.")
            if integration._needs_refresh(rejected_access_token_sha256):
                try:
                    integration._refresh(source=source)
                    refreshed = True
                except CodexReauthRequired as error:
                    integration._mark_reauth_required(str(error))
                    reauth_error = error
        if reauth_error is not None:
            raise reauth_error
        return integration.access_grant(refreshed=refreshed)

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

    def access_grant(self, *, refreshed: bool) -> CodexAccessGrant:
        access_token = _optional_str(self.integration.sensitive_config.get("access_token"))
        if access_token is None:
            raise CodexReauthRequired("The ChatGPT account must be reconnected.")
        return CodexAccessGrant(
            access_token=access_token,
            account_id=self.account_id,
            plan_type=self.plan_type,
            expires_at=self._expires_at() or timezone.now(),
            refreshed=refreshed,
        )

    def _access_token_expired(self) -> bool:
        expires_at = self._expires_at()
        return expires_at is None or timezone.now() + ACCESS_TOKEN_REFRESH_MARGIN >= expires_at

    def disconnect(self, *, source: str) -> None:
        with transaction.atomic():
            self._lock_user(self.integration.user_id)
            current = self.for_user(self.integration.user_id)
            if current is None:
                return
            refresh_token = _optional_str(current.integration.sensitive_config.get("refresh_token"))
            if refresh_token is not None:
                revoke_codex_refresh_token(refresh_token, source=source)
            current.integration.delete()

    def _needs_refresh(self, rejected_access_token_sha256: str | None) -> bool:
        if self._access_token_expired():
            return True
        if rejected_access_token_sha256 is None:
            return False
        stored = _optional_str(self.integration.sensitive_config.get("access_token"))
        return stored is None or access_token_fingerprint(stored) == rejected_access_token_sha256

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
            "access_token_expires_at": tokens.expires_at.isoformat(),
        }
