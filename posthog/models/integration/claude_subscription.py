"""A user's stored Claude subscription token for cloud agent runs.

A user can store one token, the one that `claude setup-token` prints. It lives on one
`UserIntegration` row, encrypted in `sensitive_config`. Only server and worker code reads it back,
through `ClaudeSubscriptionStore.resolve_secret`. No route returns it.
"""

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from django.db import connection, transaction
from django.utils import timezone

import posthoganalytics

from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception
from posthog.models.user_integration import UserIntegration

if TYPE_CHECKING:
    from posthog.models.user import User

# Provider terms for server-side use of a Claude subscription token are not final, so storage stays off
# for every organization that this flag does not name.
CLAUDE_SUBSCRIPTION_STORAGE_FEATURE_FLAG = "cloud-agents-claude-subscription-storage"

CLAUDE_SUBSCRIPTION_KIND = UserIntegration.IntegrationKind.CLAUDE_SUBSCRIPTION.value
TOKEN_SUFFIX_LENGTH = 4
# The suffix is shown to the user, so a shorter token would have most of its characters on display.
MIN_TOKEN_LENGTH = 20
MAX_TOKEN_LENGTH = 1024

ANTHROPIC_SECRET_PREFIX = "sk-ant-"
CLAUDE_SUBSCRIPTION_TOKEN_PREFIX = "sk-ant-oat"


class InvalidClaudeSubscriptionToken(Exception):
    """The token has the wrong format. The message is safe to show to the user and never holds the token."""


@frozen
class ClaudeSubscriptionSummary:
    token_suffix: str
    connected_at: datetime
    last_used_at: datetime | None


def claude_subscription_storage_enabled(user: "User", organization_id: str | int | UUID | None = None) -> bool:
    organization_id = str(organization_id or user.current_organization_id)
    try:
        enabled = posthoganalytics.feature_enabled(
            CLAUDE_SUBSCRIPTION_STORAGE_FEATURE_FLAG,
            str(user.distinct_id),
            groups={"organization": organization_id},
            group_properties={"organization": {"id": organization_id}},
            only_evaluate_locally=False,
            send_feature_flag_events=False,
        )
    except Exception as error:
        capture_exception(error)
        return False
    return bool(enabled)


def validate_token_format(token: str) -> None:
    if not MIN_TOKEN_LENGTH <= len(token) <= MAX_TOKEN_LENGTH or any(character.isspace() for character in token):
        raise InvalidClaudeSubscriptionToken("This does not look like a valid token. Check that you copied all of it.")
    if token.startswith(ANTHROPIC_SECRET_PREFIX) and not token.startswith(CLAUDE_SUBSCRIPTION_TOKEN_PREFIX):
        raise InvalidClaudeSubscriptionToken(
            "This is an Anthropic API key, not a Claude subscription token. "
            "Run `claude setup-token` to get a subscription token."
        )
    if not token.startswith(CLAUDE_SUBSCRIPTION_TOKEN_PREFIX):
        raise InvalidClaudeSubscriptionToken(
            "A Claude subscription token starts with `sk-ant-oat`. Run `claude setup-token` to get one."
        )


class ClaudeSubscriptionStore:
    """The `UserIntegration` row that holds a user's Claude subscription token: one row per user."""

    @classmethod
    def for_user(cls, user_id: int) -> ClaudeSubscriptionSummary | None:
        row = UserIntegration.objects.filter(user_id=user_id, kind=CLAUDE_SUBSCRIPTION_KIND).first()
        return None if row is None else cls._summary(row)

    @classmethod
    def has(cls, user_id: int) -> bool:
        return UserIntegration.objects.filter(user_id=user_id, kind=CLAUDE_SUBSCRIPTION_KIND).exists()

    @classmethod
    def connect(cls, user_id: int, token: str) -> ClaudeSubscriptionSummary:
        """Store the token in place of any stored one.

        Raises `InvalidClaudeSubscriptionToken`, and stores nothing then. No provider call checks the
        token, because no documented endpoint accepts one for a check.
        """
        token = token.strip()
        validate_token_format(token)
        with transaction.atomic():
            cls._lock_user(user_id)
            row, _ = UserIntegration.objects.update_or_create(
                user_id=user_id,
                kind=CLAUDE_SUBSCRIPTION_KIND,
                defaults={
                    "integration_id": UserIntegration.IntegrationKind.CLAUDE_SUBSCRIPTION.value,
                    "config": {
                        "token_suffix": token[-TOKEN_SUFFIX_LENGTH:],
                        "connected_at": timezone.now().isoformat(),
                        "last_used_at": None,
                    },
                    "sensitive_config": {"secret": token},
                },
            )
        return cls._summary(row)

    @classmethod
    def disconnect(cls, user_id: int) -> bool:
        deleted, _ = UserIntegration.objects.filter(user_id=user_id, kind=CLAUDE_SUBSCRIPTION_KIND).delete()
        return deleted > 0

    @classmethod
    def resolve_secret(cls, user_id: int) -> str | None:
        """The stored token, for server and worker code only. Never return the result from an API route."""
        with transaction.atomic():
            row = (
                UserIntegration.objects.select_for_update()
                .filter(user_id=user_id, kind=CLAUDE_SUBSCRIPTION_KIND)
                .first()
            )
            if row is None:
                return None
            secret = row.sensitive_config.get("secret")
            if not isinstance(secret, str) or not secret:
                return None
            row.config = {**row.config, "last_used_at": timezone.now().isoformat()}
            row.save(update_fields=["config", "updated_at"])
        return secret

    @classmethod
    def _lock_user(cls, user_id: int) -> None:
        # Row locks cannot protect the first connection because its record does not exist yet.
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_advisory_xact_lock(%s, hashtext(%s))",
                [user_id, f"user_integration:{CLAUDE_SUBSCRIPTION_KIND}"],
            )

    @classmethod
    def _summary(cls, row: UserIntegration) -> ClaudeSubscriptionSummary:
        return ClaudeSubscriptionSummary(
            token_suffix=str(row.config.get("token_suffix") or ""),
            connected_at=cls._parse_datetime(row.config.get("connected_at")) or row.created_at,
            last_used_at=cls._parse_datetime(row.config.get("last_used_at")),
        )

    @staticmethod
    def _parse_datetime(value: object) -> datetime | None:
        if not isinstance(value, str):
            return None
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
