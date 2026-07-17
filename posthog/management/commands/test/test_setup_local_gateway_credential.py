from io import StringIO

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.core.management import call_command
from django.core.management.base import CommandError

from posthog.models.project_secret_api_key import ProjectSecretAPIKey
from posthog.models.utils import hash_key_value

_PHS = "phs_localgatewaye2elocalgatewaye2e0001"
_CMD = "setup_local_gateway_credential"
_LABEL = "local-gateway-e2e"
# Patch the publish at the point of use so the test needs no Redis.
_PUBLISH = "posthog.management.commands.setup_local_gateway_credential.project_gateway_credential"


class TestSetupLocalGatewayCredentialCommand(BaseTest):
    def _run(self, *args: str) -> tuple[str, MagicMock]:
        out = StringIO()
        with patch(_PUBLISH) as publish:
            call_command(_CMD, *args, stdout=out)
        return out.getvalue(), publish

    def test_enables_team_provisions_key_and_publishes(self) -> None:
        self.assertIsNone(self.team.llm_gateway_enabled_at)
        out, publish = self._run("--phs", _PHS, "--team", str(self.team.id))

        self.team.refresh_from_db()
        self.assertIsNotNone(self.team.llm_gateway_enabled_at)
        self.assertIsNone(self.team.llm_gateway_revoked_at)

        key = ProjectSecretAPIKey.objects.get(team=self.team, label=_LABEL)
        self.assertEqual(key.secure_value, hash_key_value(_PHS))
        self.assertEqual(key.scopes, ["llm_gateway:read"])

        publish.assert_called_once_with(key)
        self.assertIn(f"__GATEWAY_E2E_TEAM_ID__={self.team.id}", out)

    def test_clears_a_prior_revoke(self) -> None:
        self._run("--phs", _PHS, "--team", str(self.team.id))
        self.team.refresh_from_db()
        # enable + unrevoke both ran, so the team is admissible.
        self.assertIsNotNone(self.team.llm_gateway_enabled_at)
        self.assertIsNone(self.team.llm_gateway_revoked_at)

    def test_rerun_is_idempotent_and_rotates_in_place(self) -> None:
        self._run("--phs", _PHS, "--team", str(self.team.id))
        rotated = "phs_rotatedrotatedrotatedrotated01"
        self._run("--phs", rotated, "--team", str(self.team.id))

        keys = ProjectSecretAPIKey.objects.filter(team=self.team, label=_LABEL)
        self.assertEqual(keys.count(), 1)
        self.assertEqual(keys.get().secure_value, hash_key_value(rotated))

    def test_defaults_to_lowest_pk_team(self) -> None:
        out, _ = self._run("--phs", _PHS)
        self.assertIn("__GATEWAY_E2E_TEAM_ID__=", out)

    @patch("posthog.management.commands.setup_local_gateway_credential.settings")
    def test_refuses_against_cloud(self, mock_settings: MagicMock) -> None:
        mock_settings.CLOUD_DEPLOYMENT = True
        with self.assertRaises(CommandError):
            self._run("--phs", _PHS, "--team", str(self.team.id))
