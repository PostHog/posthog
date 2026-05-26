from posthog.test.base import BaseTest

from django.db import connection

from posthog.models.team.extensions import get_or_create_team_extension

from products.conversations.backend.models import TeamConversationsSlackConfig
from products.conversations.backend.support_slack import (
    clear_supporthog_slack_token,
    get_support_slack_bot_token,
    save_supporthog_slack_token,
)


class TestSlackTokenStorage(BaseTest):
    def test_get_returns_empty_string_when_no_token(self):
        assert get_support_slack_bot_token(self.team) == ""

    def test_save_stores_token_in_extension_model(self):
        save_supporthog_slack_token(
            team=self.team,
            user=self.user,
            is_impersonated_session=False,
            bot_token="xoxb-test-token",
            slack_team_id="T_SAVE",
        )

        assert get_support_slack_bot_token(self.team) == "xoxb-test-token"

    def test_save_sets_slack_enabled_and_team_id(self):
        save_supporthog_slack_token(
            team=self.team,
            user=self.user,
            is_impersonated_session=False,
            bot_token="xoxb-test-token",
            slack_team_id="T_SETTINGS",
        )

        self.team.refresh_from_db()
        settings = self.team.conversations_settings or {}
        assert settings["slack_enabled"] is True
        assert "slack_team_id" not in settings

        config = TeamConversationsSlackConfig.objects.get(team=self.team)
        assert config.slack_team_id == "T_SETTINGS"

    def test_token_not_in_conversations_settings_json(self):
        save_supporthog_slack_token(
            team=self.team,
            user=self.user,
            is_impersonated_session=False,
            bot_token="xoxb-secret",
            slack_team_id="T_NOLEAK",
        )

        self.team.refresh_from_db()
        settings = self.team.conversations_settings or {}
        assert "slack_bot_token" not in settings

    def test_token_encrypted_at_rest(self):
        save_supporthog_slack_token(
            team=self.team,
            user=self.user,
            is_impersonated_session=False,
            bot_token="xoxb-plaintext-check",
            slack_team_id="T_ENC",
        )

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT slack_bot_token FROM posthog_conversations_slack_config WHERE team_id = %s",
                [self.team.pk],
            )
            raw_value = cursor.fetchone()[0]

        assert raw_value != "xoxb-plaintext-check"
        assert "xoxb-plaintext-check" not in (raw_value or "")

    def test_clear_removes_token(self):
        save_supporthog_slack_token(
            team=self.team,
            user=self.user,
            is_impersonated_session=False,
            bot_token="xoxb-to-clear",
            slack_team_id="T_CLEAR",
        )

        clear_supporthog_slack_token(
            team=self.team,
            user=self.user,
            is_impersonated_session=False,
        )

        assert get_support_slack_bot_token(self.team) == ""

    def test_clear_sets_slack_enabled_false_and_clears_config(self):
        save_supporthog_slack_token(
            team=self.team,
            user=self.user,
            is_impersonated_session=False,
            bot_token="xoxb-to-disable",
            slack_team_id="T_DISABLE",
        )

        clear_supporthog_slack_token(
            team=self.team,
            user=self.user,
            is_impersonated_session=False,
        )

        self.team.refresh_from_db()
        settings = self.team.conversations_settings or {}
        assert settings["slack_enabled"] is False

        config = TeamConversationsSlackConfig.objects.get(team=self.team)
        assert config.slack_team_id is None
        assert config.slack_bot_token is None

    def test_clear_noop_when_no_token(self):
        self.team.conversations_settings = {"slack_enabled": True}
        self.team.save()

        clear_supporthog_slack_token(
            team=self.team,
            user=self.user,
            is_impersonated_session=False,
        )

        self.team.refresh_from_db()
        assert self.team.conversations_settings["slack_enabled"] is True

    def test_save_overwrites_existing_token(self):
        save_supporthog_slack_token(
            team=self.team,
            user=self.user,
            is_impersonated_session=False,
            bot_token="xoxb-first",
            slack_team_id="T_FIRST",
        )
        save_supporthog_slack_token(
            team=self.team,
            user=self.user,
            is_impersonated_session=False,
            bot_token="xoxb-second",
            slack_team_id="T_SECOND",
        )

        assert get_support_slack_bot_token(self.team) == "xoxb-second"
        config = TeamConversationsSlackConfig.objects.get(team=self.team)
        assert config.slack_team_id == "T_SECOND"

    def test_extension_auto_created_on_team_creation(self):
        config = get_or_create_team_extension(self.team, TeamConversationsSlackConfig)
        assert config.team_id == self.team.pk
        assert config.slack_bot_token is None
