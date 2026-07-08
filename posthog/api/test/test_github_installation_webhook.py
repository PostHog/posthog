import hmac
import json
import hashlib

from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings

from parameterized import parameterized
from rest_framework.test import APIClient

from posthog.models.github_integration_base import GitHubIntegrationBase
from posthog.models.integration import GitHubIntegration, Integration
from posthog.models.organization import Organization
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.models.user_integration import UserIntegration


def _signature(payload: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()


class TestGitHubInstallationReferenceHelpers(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")
        self.user = User.objects.create(email="helper@example.com", distinct_id="helper-1")

    def _team_integration(self, installation_id: str = "12345") -> Integration:
        return Integration.objects.create(
            team=self.team, kind="github", integration_id=installation_id, config={}, sensitive_config={}
        )

    def _user_integration(self, installation_id: str = "12345") -> UserIntegration:
        return UserIntegration.objects.create(
            user=self.user, kind="github", integration_id=installation_id, config={}, sensitive_config={}
        )

    def test_reference_count_zero_when_none(self):
        self.assertEqual(GitHubIntegrationBase.installation_reference_count("12345"), 0)

    def test_reference_count_team_only(self):
        self._team_integration()
        self.assertEqual(GitHubIntegrationBase.installation_reference_count("12345"), 1)

    def test_reference_count_user_only(self):
        self._user_integration()
        self.assertEqual(GitHubIntegrationBase.installation_reference_count("12345"), 1)

    def test_reference_count_across_both_tables(self):
        self._team_integration()
        self._user_integration()
        self.assertEqual(GitHubIntegrationBase.installation_reference_count("12345"), 2)

    def test_reference_count_respects_team_exclusion(self):
        team_integration = self._team_integration()
        self.assertEqual(
            GitHubIntegrationBase.installation_reference_count(
                "12345", exclude_team_integration_id=team_integration.id
            ),
            0,
        )

    def test_reference_count_respects_user_exclusion(self):
        user_integration = self._user_integration()
        self.assertEqual(
            GitHubIntegrationBase.installation_reference_count(
                "12345", exclude_user_integration_id=user_integration.id
            ),
            0,
        )

    @parameterized.expand(
        [
            ("removed_204", 204, True),
            ("already_gone_404", 404, True),
            ("unexpected_500", 500, False),
        ]
    )
    @override_settings(GITHUB_APP_CLIENT_ID="cid", GITHUB_APP_PRIVATE_KEY="key")
    @patch("posthog.models.github_integration_base.GitHubIntegrationBase.client_request")
    def test_uninstall_app_installation_status_handling(self, _name, status_code, expected, mock_client_request):
        mock_client_request.return_value = MagicMock(status_code=status_code)
        self.assertEqual(GitHubIntegration.uninstall_app_installation("12345"), expected)
        mock_client_request.assert_called_once_with("installations/12345", method="DELETE", timeout=10)

    @override_settings(GITHUB_APP_CLIENT_ID="cid", GITHUB_APP_PRIVATE_KEY="key")
    @patch("posthog.models.github_integration_base.GitHubIntegrationBase.client_request")
    def test_uninstall_app_installation_false_when_request_raises(self, mock_client_request):
        mock_client_request.side_effect = Exception("network error")
        self.assertFalse(GitHubIntegration.uninstall_app_installation("12345"))

    @override_settings(GITHUB_APP_CLIENT_ID="", GITHUB_APP_PRIVATE_KEY="")
    def test_uninstall_app_installation_false_when_not_configured(self):
        self.assertFalse(GitHubIntegration.uninstall_app_installation("12345"))

    @patch("posthog.models.integration.GitHubIntegration.uninstall_app_installation")
    def test_uninstall_if_last_reference_skips_when_references_remain(self, mock_uninstall):
        self._team_integration()
        self.assertFalse(GitHubIntegration.uninstall_if_last_reference("12345"))
        mock_uninstall.assert_not_called()

    @patch("posthog.models.integration.GitHubIntegration.uninstall_app_installation")
    def test_uninstall_if_last_reference_uninstalls_when_none_remain(self, mock_uninstall):
        mock_uninstall.return_value = True
        self.assertTrue(GitHubIntegration.uninstall_if_last_reference("12345"))
        mock_uninstall.assert_called_once_with("12345")


class TestGitHubInstallationWebhook(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")
        self.user = User.objects.create(email="webhook@example.com", distinct_id="webhook-1")
        self.webhook_secret = "test-webhook-secret"

    def _post(self, payload: dict, event_type: str = "installation"):
        payload_bytes = json.dumps(payload).encode("utf-8")
        return self.client.post(
            "/webhooks/github/",
            data=payload_bytes,
            content_type="application/json",
            headers={
                "x-hub-signature-256": _signature(payload_bytes, self.webhook_secret),
                "x-github-event": event_type,
            },
        )

    def _team_integration(self, installation_id: str = "12345") -> Integration:
        return Integration.objects.create(
            team=self.team, kind="github", integration_id=installation_id, config={}, sensitive_config={}
        )

    def _user_integration(self, installation_id: str = "12345") -> UserIntegration:
        return UserIntegration.objects.create(
            user=self.user, kind="github", integration_id=installation_id, config={}, sensitive_config={}
        )

    @patch("products.tasks.backend.facade.webhooks.get_github_webhook_secret")
    @patch("posthog.models.github_integration_base.GitHubIntegrationBase.client_request")
    def test_deleted_removes_all_rows_and_does_not_call_github(self, mock_client_request, mock_get_secret):
        mock_get_secret.return_value = self.webhook_secret
        self._team_integration("12345")
        self._user_integration("12345")

        response = self._post({"action": "deleted", "installation": {"id": 12345}})

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Integration.objects.filter(kind="github", integration_id="12345").exists())
        self.assertFalse(UserIntegration.objects.filter(kind="github", integration_id="12345").exists())
        # Inbound side must never call out to GitHub (loop prevention).
        mock_client_request.assert_not_called()

    @patch("products.tasks.backend.facade.webhooks.get_github_webhook_secret")
    def test_deleted_with_no_matching_rows_is_idempotent(self, mock_get_secret):
        mock_get_secret.return_value = self.webhook_secret

        response = self._post({"action": "deleted", "installation": {"id": 99999}})

        self.assertEqual(response.status_code, 200)

    @parameterized.expand([("suspend",), ("unsuspend",)])
    @patch("products.tasks.backend.facade.webhooks.get_github_webhook_secret")
    def test_reversible_action_does_not_delete_rows(self, action, mock_get_secret):
        mock_get_secret.return_value = self.webhook_secret
        self._team_integration("12345")

        response = self._post({"action": action, "installation": {"id": 12345}})

        self.assertEqual(response.status_code, 200)
        self.assertTrue(Integration.objects.filter(kind="github", integration_id="12345").exists())

    @patch("products.tasks.backend.facade.webhooks.get_github_webhook_secret")
    def test_missing_installation_id_returns_200(self, mock_get_secret):
        mock_get_secret.return_value = self.webhook_secret

        response = self._post({"action": "deleted"})

        self.assertEqual(response.status_code, 200)

    @patch("products.tasks.backend.facade.webhooks.get_github_webhook_secret")
    def test_invalid_signature_returns_403_and_keeps_rows(self, mock_get_secret):
        mock_get_secret.return_value = self.webhook_secret
        self._team_integration("12345")

        payload_bytes = json.dumps({"action": "deleted", "installation": {"id": 12345}}).encode("utf-8")
        response = self.client.post(
            "/webhooks/github/",
            data=payload_bytes,
            content_type="application/json",
            headers={"x-hub-signature-256": "sha256=wrong", "x-github-event": "installation"},
        )

        self.assertEqual(response.status_code, 403)
        self.assertTrue(Integration.objects.filter(kind="github", integration_id="12345").exists())
