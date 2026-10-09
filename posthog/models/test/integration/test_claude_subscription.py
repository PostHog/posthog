from datetime import UTC, datetime

import time_machine
from posthog.test.base import BaseTest
from unittest.mock import patch

from django.db import connection
from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models.integration.claude_subscription import (
    ClaudeSubscriptionStore,
    InvalidClaudeSubscriptionToken,
    claude_subscription_storage_enabled,
    validate_token_format,
)
from posthog.models.user import User
from posthog.models.user_integration import UserIntegration

FROZEN_NOW = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)

CLAUDE_TOKEN = "sk-ant-oat01-not-a-real-token-0003"
OTHER_CLAUDE_TOKEN = "sk-ant-oat01-not-a-real-token-0004"
ANTHROPIC_KEY = "sk-ant-api03-not-a-real-key-0001"


class TestValidateTokenFormat(SimpleTestCase):
    @parameterized.expand(
        [
            ("typical", CLAUDE_TOKEN),
            ("shortest", "sk-ant-oat" + "a" * 10),
            ("longest", "sk-ant-oat" + "a" * 1014),
        ]
    )
    def test_accepts_a_subscription_token(self, _name: str, token: str) -> None:
        validate_token_format(token)

    @parameterized.expand(
        [
            ("anthropic_api_key", ANTHROPIC_KEY, "Anthropic API key"),
            ("other_provider_key", "sk-proj-not-a-real-key-000000002", "starts with `sk-ant-oat`"),
            ("no_prefix", "not-a-real-token-000000000004", "starts with `sk-ant-oat`"),
            ("too_short", "sk-ant-oat" + "a" * 9, "valid token"),
            ("too_long", "sk-ant-oat" + "a" * 1015, "valid token"),
            ("inner_whitespace", "sk-ant-oat01-not-a-real token-0005", "valid token"),
            ("surrounding_whitespace", f" {CLAUDE_TOKEN}\n", "valid token"),
            ("empty", "", "valid token"),
        ]
    )
    def test_rejects_a_token_of_the_wrong_shape_without_echoing_it(
        self, _name: str, token: str, expected_message: str
    ) -> None:
        with self.assertRaises(InvalidClaudeSubscriptionToken) as raised:
            validate_token_format(token)

        message = str(raised.exception)
        assert expected_message in message
        if token:
            assert token not in message


class TestClaudeSubscriptionStore(BaseTest):
    def _raw_sensitive_config(self) -> str:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT sensitive_config::text FROM posthog_user_integration WHERE user_id = %s AND kind = %s",
                [self.user.id, "claude_subscription"],
            )
            return cursor.fetchone()[0]

    @time_machine.travel(FROZEN_NOW, tick=False)
    def test_connect_strips_surrounding_whitespace_and_stores_the_token_encrypted(self) -> None:
        assert ClaudeSubscriptionStore.for_user(self.user.id) is None
        assert not ClaudeSubscriptionStore.has(self.user.id)

        summary = ClaudeSubscriptionStore.connect(self.user.id, f"  {CLAUDE_TOKEN}\n")

        assert summary.token_suffix == "0003"
        assert summary.connected_at == FROZEN_NOW
        assert summary.last_used_at is None
        assert CLAUDE_TOKEN not in repr(summary)
        assert ClaudeSubscriptionStore.for_user(self.user.id) == summary
        assert ClaudeSubscriptionStore.has(self.user.id)

        row = UserIntegration.objects.get(user=self.user, kind="claude_subscription")
        assert row.sensitive_config == {"secret": CLAUDE_TOKEN}
        assert set(row.config) == {"token_suffix", "connected_at", "last_used_at"}
        assert CLAUDE_TOKEN not in str(row.config)
        assert row.integration_id == "claude_subscription"
        assert CLAUDE_TOKEN not in self._raw_sensitive_config()

    def test_connect_replaces_the_stored_token_and_resets_the_last_use(self) -> None:
        ClaudeSubscriptionStore.connect(self.user.id, CLAUDE_TOKEN)
        ClaudeSubscriptionStore.resolve_secret(self.user.id)

        summary = ClaudeSubscriptionStore.connect(self.user.id, OTHER_CLAUDE_TOKEN)

        assert summary.token_suffix == "0004"
        assert summary.last_used_at is None
        assert UserIntegration.objects.filter(user=self.user, kind="claude_subscription").count() == 1
        assert ClaudeSubscriptionStore.resolve_secret(self.user.id) == OTHER_CLAUDE_TOKEN

    @parameterized.expand([("anthropic_api_key", ANTHROPIC_KEY), ("too_short", "sk-ant-oat01")])
    def test_connect_with_an_invalid_token_stores_nothing_and_keeps_the_old_token(self, _name: str, token: str) -> None:
        with self.assertRaises(InvalidClaudeSubscriptionToken):
            ClaudeSubscriptionStore.connect(self.user.id, token)
        assert not ClaudeSubscriptionStore.has(self.user.id)

        ClaudeSubscriptionStore.connect(self.user.id, CLAUDE_TOKEN)
        with self.assertRaises(InvalidClaudeSubscriptionToken):
            ClaudeSubscriptionStore.connect(self.user.id, token)

        assert ClaudeSubscriptionStore.resolve_secret(self.user.id) == CLAUDE_TOKEN

    def test_resolve_secret_returns_the_token_and_records_the_use(self) -> None:
        assert ClaudeSubscriptionStore.resolve_secret(self.user.id) is None
        with time_machine.travel(FROZEN_NOW, tick=False):
            ClaudeSubscriptionStore.connect(self.user.id, CLAUDE_TOKEN)
        used_at = datetime(2026, 3, 2, 9, 30, tzinfo=UTC)

        with time_machine.travel(used_at, tick=False):
            secret = ClaudeSubscriptionStore.resolve_secret(self.user.id)

        assert secret == CLAUDE_TOKEN
        summary = ClaudeSubscriptionStore.for_user(self.user.id)
        assert summary is not None
        assert summary.last_used_at == used_at
        assert summary.connected_at == FROZEN_NOW

    def test_one_user_cannot_reach_the_token_of_another_user(self) -> None:
        other = User.objects.create_and_join(self.organization, "other@example.com", None)
        ClaudeSubscriptionStore.connect(self.user.id, CLAUDE_TOKEN)

        assert ClaudeSubscriptionStore.for_user(other.id) is None
        assert ClaudeSubscriptionStore.resolve_secret(other.id) is None
        assert ClaudeSubscriptionStore.disconnect(other.id) is False

        ClaudeSubscriptionStore.connect(other.id, OTHER_CLAUDE_TOKEN)
        other_summary = ClaudeSubscriptionStore.for_user(other.id)
        assert other_summary is not None
        assert other_summary.token_suffix == "0004"
        assert ClaudeSubscriptionStore.disconnect(other.id) is True
        assert ClaudeSubscriptionStore.disconnect(other.id) is False
        assert ClaudeSubscriptionStore.resolve_secret(other.id) is None
        assert ClaudeSubscriptionStore.resolve_secret(self.user.id) == CLAUDE_TOKEN

    @parameterized.expand(
        [
            ("enabled", True, None, True),
            ("disabled", False, None, False),
            ("no_answer", None, None, False),
            ("check_failed", None, RuntimeError("down"), False),
        ]
    )
    def test_storage_flag_is_scoped_to_the_organization_and_fails_closed(
        self, _name: str, flag_value: bool | None, error: Exception | None, expected: bool
    ) -> None:
        with patch(
            "posthog.models.integration.claude_subscription.posthoganalytics.feature_enabled",
            return_value=flag_value,
            side_effect=error,
        ) as feature_enabled:
            assert claude_subscription_storage_enabled(self.user) is expected

        assert feature_enabled.call_args.args[0] == "cloud-agents-claude-subscription-storage"
        assert feature_enabled.call_args.kwargs["groups"] == {"organization": str(self.organization.id)}
