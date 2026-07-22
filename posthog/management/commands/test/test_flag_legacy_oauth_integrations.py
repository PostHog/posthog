import json
import base64

from posthog.test.base import BaseTest

from django.core.management import call_command
from django.test import override_settings

from parameterized import parameterized

from posthog.models.integration import CONFIG_LEGACY_OAUTH_CLIENT, Integration


def _id_token(audience: str | list[str]) -> str:
    payload = base64.urlsafe_b64encode(json.dumps({"aud": audience, "oid": "user-oid"}).encode()).decode().rstrip("=")
    return f"header.{payload}.signature"


@override_settings(BING_ADS_CLIENT_ID="current-app-id")
class TestFlagLegacyOauthIntegrations(BaseTest):
    @parameterized.expand(
        [
            # Connected through the superseded app: this is the population that breaks on retirement.
            ("legacy_client", _id_token("old-app-id"), False, True),
            # Already on the current app - a stale flag here would nag a team with nothing to do.
            ("current_client_clears_stale_flag", _id_token("current-app-id"), True, False),
            # `aud` is a string or a list per RFC 7519. Reading only the string shape would drop
            # list-shaped tokens into "unknown", silently leaving those teams out of the campaign.
            ("legacy_client_in_aud_list", _id_token(["old-app-id"]), False, True),
            ("current_client_in_aud_list", _id_token(["current-app-id", "other-audience"]), True, False),
            # Nothing to read, so the command must not guess either way.
            ("no_id_token", None, False, False),
        ]
    )
    def test_flags_integrations_by_issuing_client(self, _name, id_token, initial_flag, expected_flag):
        config = {"expires_in": 1000}
        if initial_flag:
            config[CONFIG_LEGACY_OAUTH_CLIENT] = True
        integration = Integration.objects.create(
            team=self.team,
            kind="bing-ads",
            integration_id="user-oid",
            config=config,
            sensitive_config={"access_token": "token", "id_token": id_token},
        )

        call_command("flag_legacy_oauth_integrations")

        integration.refresh_from_db()
        assert integration.config.get(CONFIG_LEGACY_OAUTH_CLIENT, False) == expected_flag

    def test_dry_run_reports_without_writing(self):
        integration = Integration.objects.create(
            team=self.team,
            kind="bing-ads",
            integration_id="user-oid",
            config={},
            sensitive_config={"access_token": "token", "id_token": _id_token("old-app-id")},
        )

        call_command("flag_legacy_oauth_integrations", "--dry-run")

        integration.refresh_from_db()
        assert CONFIG_LEGACY_OAUTH_CLIENT not in integration.config
