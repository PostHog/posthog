import re
import hashlib
from datetime import datetime, timedelta

from django.db import connection, models, transaction
from django.utils import timezone

import structlog

from posthog.models.user_integration import UserIntegration

logger = structlog.get_logger(__name__)

CLAUDE_SETUP_TOKEN_PATTERN = re.compile(r"^sk-ant-oat01-\S{29,}$")
CLAUDE_SETUP_TOKEN_MAX_LENGTH = 4096
CLAUDE_INTEGRATION_ID = "setup_token"
CLAUDE_SETUP_TOKEN_LIFETIME = timedelta(days=365)


class ClaudeIntegrationStatus(models.TextChoices):
    CONNECTED = "connected", "Token connected"
    REAUTH_REQUIRED = "reauth_required", "New token required"
    NOT_CONNECTED = "not_connected", "No token"


STATUS_CONNECTED = ClaudeIntegrationStatus.CONNECTED.value
STATUS_REAUTH_REQUIRED = ClaudeIntegrationStatus.REAUTH_REQUIRED.value
STATUS_NOT_CONNECTED = ClaudeIntegrationStatus.NOT_CONNECTED.value


class ClaudeAuthError(Exception):
    pass


class ClaudeReauthRequired(ClaudeAuthError):
    pass


class ClaudeTokenRejected(ClaudeReauthRequired):
    def __init__(self, message: str, *, token_age_days: int | None) -> None:
        super().__init__(message)
        self.token_age_days = token_age_days


def claude_token_fingerprint(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def parse_claude_setup_token(raw: object) -> str:
    token = raw.strip() if isinstance(raw, str) else ""
    if len(token) > CLAUDE_SETUP_TOKEN_MAX_LENGTH or not CLAUDE_SETUP_TOKEN_PATTERN.match(token):
        raise ClaudeAuthError("Paste the full token from `claude setup-token`. It starts with sk-ant-oat01-.")
    return token


class ClaudeUserIntegration:
    KIND = UserIntegration.IntegrationKind.CLAUDE

    def __init__(self, integration: UserIntegration) -> None:
        self.integration = integration

    @classmethod
    def for_user(cls, user_id: int) -> "ClaudeUserIntegration | None":
        row = UserIntegration.objects.filter(user_id=user_id, kind=cls.KIND).first()
        return cls(row) if row is not None else None

    @classmethod
    def _lock_user(cls, user_id: int) -> None:
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s, hashtext(%s))", [user_id, "user_integration:claude"])

    @classmethod
    def connect(cls, user_id: int, token: str) -> "ClaudeUserIntegration":
        with transaction.atomic():
            cls._lock_user(user_id)
            row, _ = UserIntegration.objects.update_or_create(
                user_id=user_id,
                kind=cls.KIND,
                defaults={
                    "integration_id": CLAUDE_INTEGRATION_ID,
                    "config": {"status": STATUS_CONNECTED, "connected_at": timezone.now().isoformat()},
                    "sensitive_config": {"token": token},
                },
            )
        return cls(row)

    @classmethod
    def issue_token(cls, user_id: int, *, rejected_token_sha256: str | None) -> str:
        reauth_error: ClaudeTokenRejected | None = None
        token: str | None = None
        with transaction.atomic():
            cls._lock_user(user_id)
            row = UserIntegration.objects.select_for_update().filter(user_id=user_id, kind=cls.KIND).first()
            if row is None:
                raise ClaudeReauthRequired("No Claude account is connected.")
            integration = cls(row)
            token = integration._stored_token()
            if not integration.is_connected() or token is None:
                raise ClaudeReauthRequired("The Claude account must be reconnected.")
            if rejected_token_sha256 is not None and claude_token_fingerprint(token) == rejected_token_sha256:
                token_age_days = integration._token_age_days()
                integration._mark_reauth_required("Anthropic rejected the token.", rejected_token_sha256)
                reauth_error = ClaudeTokenRejected(
                    "Anthropic rejected the Claude token.", token_age_days=token_age_days
                )
        if reauth_error is not None:
            raise reauth_error
        return token

    @property
    def status(self) -> str:
        return str(self.integration.config.get("status") or STATUS_REAUTH_REQUIRED)

    @property
    def connected_at(self) -> str | None:
        value = self.integration.config.get("connected_at")
        return value if isinstance(value, str) and value else None

    @property
    def expires_at(self) -> str | None:
        connected_at = self._connected_at_datetime()
        if not self.is_connected() or connected_at is None:
            return None
        return (connected_at + CLAUDE_SETUP_TOKEN_LIFETIME).isoformat()

    def is_connected(self) -> bool:
        return self.status == STATUS_CONNECTED

    def rejects(self, token: str) -> bool:
        rejected = self.integration.config.get("rejected_token_sha256")
        return (
            self.status == STATUS_REAUTH_REQUIRED
            and isinstance(rejected, str)
            and claude_token_fingerprint(token) == rejected
        )

    def disconnect(self) -> None:
        with transaction.atomic():
            self._lock_user(self.integration.user_id)
            UserIntegration.objects.filter(user_id=self.integration.user_id, kind=self.KIND).delete()

    def _stored_token(self) -> str | None:
        value = self.integration.sensitive_config.get("token")
        return value if isinstance(value, str) and value else None

    def _connected_at_datetime(self) -> datetime | None:
        value = self.connected_at
        if value is None:
            return None
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None

    def _token_age_days(self) -> int | None:
        connected_at = self._connected_at_datetime()
        return (timezone.now() - connected_at).days if connected_at is not None else None

    def _mark_reauth_required(self, reason: str, rejected_token_sha256: str) -> None:
        self.integration.sensitive_config = {}
        self.integration.config = {
            **self.integration.config,
            "status": STATUS_REAUTH_REQUIRED,
            "reauth_reason": reason,
            "rejected_token_sha256": rejected_token_sha256,
        }
        self.integration.save(update_fields=["config", "sensitive_config"])
        logger.warning("claude_subscription_reauth_required", user_id=self.integration.user_id, reason=reason)
