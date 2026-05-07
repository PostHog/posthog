from posthog.test.base import BaseTest

from django.db import connection

from parameterized import parameterized

from posthog.models.team.extensions import get_or_create_team_extension

from products.conversations.backend.models import TeamConversationsTeamsConfig
from products.conversations.backend.support_teams import (
    clear_teams_token,
    get_graph_token,
    is_trusted_teams_service_url,
    save_teams_token,
)


class TestTeamsTokenStorage(BaseTest):
    def test_save_stores_tokens_in_extension_model(self):
        save_teams_token(
            team=self.team,
            user=self.user,
            is_impersonated_session=False,
            access_token="graph-access-tok",
            refresh_token="graph-refresh-tok",
            tenant_id="tenant-123",
        )

        config = TeamConversationsTeamsConfig.objects.get(team=self.team)
        assert config.teams_graph_access_token == "graph-access-tok"
        assert config.teams_graph_refresh_token == "graph-refresh-tok"
        assert config.teams_tenant_id == "tenant-123"
        assert config.teams_token_expires_at is not None

    def test_save_sets_teams_enabled(self):
        save_teams_token(
            team=self.team,
            user=self.user,
            is_impersonated_session=False,
            access_token="tok",
            refresh_token="ref",
            tenant_id="t-1",
        )

        self.team.refresh_from_db()
        settings = self.team.conversations_settings or {}
        assert settings["teams_enabled"] is True

    def test_tokens_not_in_conversations_settings_json(self):
        save_teams_token(
            team=self.team,
            user=self.user,
            is_impersonated_session=False,
            access_token="secret-access",
            refresh_token="secret-refresh",
            tenant_id="t-noleak",
        )

        self.team.refresh_from_db()
        settings = self.team.conversations_settings or {}
        assert "teams_graph_access_token" not in settings
        assert "teams_graph_refresh_token" not in settings

    def test_tokens_encrypted_at_rest(self):
        save_teams_token(
            team=self.team,
            user=self.user,
            is_impersonated_session=False,
            access_token="plaintext-check",
            refresh_token="plaintext-ref",
            tenant_id="t-enc",
        )

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT teams_graph_access_token, teams_graph_refresh_token "
                "FROM posthog_conversations_teams_config WHERE team_id = %s",
                [self.team.pk],
            )
            raw_access, raw_refresh = cursor.fetchone()

        assert raw_access != "plaintext-check"
        assert "plaintext-check" not in (raw_access or "")
        assert raw_refresh != "plaintext-ref"
        assert "plaintext-ref" not in (raw_refresh or "")

    def test_clear_removes_tokens_and_tenant(self):
        save_teams_token(
            team=self.team,
            user=self.user,
            is_impersonated_session=False,
            access_token="tok",
            refresh_token="ref",
            tenant_id="t-clear",
        )

        clear_teams_token(
            team=self.team,
            user=self.user,
            is_impersonated_session=False,
        )

        config = TeamConversationsTeamsConfig.objects.get(team=self.team)
        assert config.teams_tenant_id is None
        assert config.teams_graph_access_token is None
        assert config.teams_graph_refresh_token is None
        assert config.teams_token_expires_at is None

    def test_clear_sets_teams_enabled_false(self):
        save_teams_token(
            team=self.team,
            user=self.user,
            is_impersonated_session=False,
            access_token="tok",
            refresh_token="ref",
            tenant_id="t-disable",
        )

        clear_teams_token(
            team=self.team,
            user=self.user,
            is_impersonated_session=False,
        )

        self.team.refresh_from_db()
        settings = self.team.conversations_settings or {}
        assert settings["teams_enabled"] is False

    def test_clear_removes_channel_settings(self):
        save_teams_token(
            team=self.team,
            user=self.user,
            is_impersonated_session=False,
            access_token="tok",
            refresh_token="ref",
            tenant_id="t-ch",
        )
        self.team.conversations_settings.update(
            {
                "teams_team_id": "grp-1",
                "teams_team_name": "Eng",
                "teams_channel_id": "ch-1",
                "teams_channel_name": "#support",
            }
        )
        self.team.save()

        clear_teams_token(
            team=self.team,
            user=self.user,
            is_impersonated_session=False,
        )

        self.team.refresh_from_db()
        settings = self.team.conversations_settings or {}
        assert "teams_team_id" not in settings
        assert "teams_channel_id" not in settings

    def test_clear_noop_when_no_tenant(self):
        self.team.conversations_settings = {"teams_enabled": True}
        self.team.save()

        clear_teams_token(
            team=self.team,
            user=self.user,
            is_impersonated_session=False,
        )

        self.team.refresh_from_db()
        assert self.team.conversations_settings["teams_enabled"] is True

    def test_save_overwrites_existing(self):
        save_teams_token(
            team=self.team,
            user=self.user,
            is_impersonated_session=False,
            access_token="first",
            refresh_token="first-ref",
            tenant_id="t-first",
        )
        save_teams_token(
            team=self.team,
            user=self.user,
            is_impersonated_session=False,
            access_token="second",
            refresh_token="second-ref",
            tenant_id="t-second",
        )

        config = TeamConversationsTeamsConfig.objects.get(team=self.team)
        assert config.teams_graph_access_token == "second"
        assert config.teams_tenant_id == "t-second"

    def test_extension_auto_created_on_team_creation(self):
        config = get_or_create_team_extension(self.team, TeamConversationsTeamsConfig)
        assert config.team_id == self.team.pk
        assert config.teams_graph_access_token is None

    def test_get_graph_token_raises_when_no_token(self):
        with self.assertRaises(ValueError, msg="No Graph API token configured"):
            get_graph_token(self.team)


class TestTrustedTeamsServiceUrl(BaseTest):
    @parameterized.expand(
        [
            ("https://smba.trafficmanager.net/teams/",),
            ("https://smba.trafficmanager.net/uk/",),
            ("https://SMBA.TrafficManager.NET/emea/",),
            ("https://smba.infra.gcs.azure.us/gov/",),
            ("https://smba.infra.gcs.azure.cn/china/",),
            ("https://api.botframework.com/",),
            ("https://foo.botframework.com/",),
        ]
    )
    def test_trusted(self, url: str) -> None:
        assert is_trusted_teams_service_url(url) is True

    @parameterized.expand(
        [
            ("",),
            ("not a url",),
            ("http://smba.trafficmanager.net/teams/",),  # http, not https
            ("https://evil.example.com/",),
            ("https://smba.trafficmanager.net.evil.com/",),  # suffix-spoof attempt
            ("https://attacker.com/smba.trafficmanager.net/",),  # path-injection attempt
            ("https://",),
        ]
    )
    def test_untrusted(self, url: str) -> None:
        assert is_trusted_teams_service_url(url) is False
