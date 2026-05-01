import time
from datetime import timedelta

from freezegun import freeze_time
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from rest_framework.exceptions import ValidationError

from posthog.models.integration import FirebaseIntegration, Integration

FAKE_KEY_INFO = {
    "type": "service_account",
    "project_id": "my-firebase-project",
    "private_key_id": "key123",
    "private_key": "-----BEGIN RSA PRIVATE KEY-----\nfake\n-----END RSA PRIVATE KEY-----",
    "client_email": "test@my-firebase-project.iam.gserviceaccount.com",
    "client_id": "123456",
    "token_uri": "https://oauth2.googleapis.com/token",
}


def _mock_credentials(token: str = "access-token-1", expiry_offset: int = 3600):
    creds = MagicMock()
    creds.token = token
    creds.expiry = MagicMock()
    creds.expiry.timestamp.return_value = time.time() + expiry_offset
    return creds


class TestFirebaseIntegration(BaseTest):
    @patch("posthog.models.integration.GoogleRequest")
    @patch("posthog.models.integration.service_account.Credentials.from_service_account_info")
    def _create_firebase_integration(self, mock_from_sa, mock_google_request, **overrides) -> Integration:
        mock_from_sa.return_value = _mock_credentials()
        key_info = overrides.pop("key_info", FAKE_KEY_INFO)
        team_id = overrides.pop("team_id", self.team.id)
        created_by = overrides.pop("created_by", None)
        return FirebaseIntegration.integration_from_key(key_info, team_id, created_by)

    def test_creates_integration(self):
        integration = self._create_firebase_integration()

        assert integration.kind == "firebase"
        assert integration.integration_id == "my-firebase-project"
        assert integration.config["project_id"] == "my-firebase-project"
        assert "expires_in" in integration.config
        assert "refreshed_at" in integration.config
        assert integration.sensitive_config["key_info"] == FAKE_KEY_INFO
        assert integration.sensitive_config["access_token"] == "access-token-1"

    def test_upserts_on_same_project(self):
        first = self._create_firebase_integration()
        second = self._create_firebase_integration()

        assert first.id == second.id

    def test_separate_integrations_for_different_projects(self):
        first = self._create_firebase_integration()

        other_key = {**FAKE_KEY_INFO, "project_id": "other-project"}
        second = self._create_firebase_integration(key_info=other_key)

        assert first.id != second.id

    @patch("posthog.models.integration.GoogleRequest")
    @patch("posthog.models.integration.service_account.Credentials.from_service_account_info")
    def test_validates_service_account_key(self, mock_from_sa, mock_google_request):
        mock_from_sa.side_effect = Exception("invalid key")

        with self.assertRaises(ValidationError):
            FirebaseIntegration.integration_from_key(FAKE_KEY_INFO, self.team.id)

    @patch("posthog.models.integration.GoogleRequest")
    @patch("posthog.models.integration.service_account.Credentials.from_service_account_info")
    def test_validates_project_id_present(self, mock_from_sa, mock_google_request):
        mock_from_sa.return_value = _mock_credentials()
        key_info_no_project = {k: v for k, v in FAKE_KEY_INFO.items() if k != "project_id"}

        with self.assertRaises(ValidationError):
            FirebaseIntegration.integration_from_key(key_info_no_project, self.team.id)

    def test_wrapper_properties(self):
        integration = self._create_firebase_integration()
        wrapper = FirebaseIntegration(integration)

        assert wrapper.project_id == "my-firebase-project"

    def test_wrapper_rejects_wrong_kind(self):
        integration = Integration.objects.create(
            team=self.team,
            kind="slack",
            config={},
            sensitive_config={},
        )

        with self.assertRaisesMessage(Exception, "FirebaseIntegration init called with Integration with wrong 'kind'"):
            FirebaseIntegration(integration)

    @freeze_time("2024-01-01T00:00:00Z")
    def test_access_token_not_expired_initially(self):
        integration = Integration.objects.create(
            team=self.team,
            kind="firebase",
            integration_id="proj",
            config={
                "project_id": "proj",
                "expires_in": 3600,
                "refreshed_at": int(time.time()),
            },
            sensitive_config={"key_info": FAKE_KEY_INFO, "access_token": "token"},
        )
        wrapper = FirebaseIntegration(integration)

        assert wrapper.access_token_expired() is False

    @freeze_time("2024-01-01T00:00:00Z")
    def test_access_token_expired_after_half_expiry(self):
        integration = Integration.objects.create(
            team=self.team,
            kind="firebase",
            integration_id="proj",
            config={
                "project_id": "proj",
                "expires_in": 3600,
                "refreshed_at": int(time.time()) - 2000,
            },
            sensitive_config={"key_info": FAKE_KEY_INFO, "access_token": "token"},
        )
        wrapper = FirebaseIntegration(integration)

        assert wrapper.access_token_expired() is True

    @freeze_time("2024-01-01T00:00:00Z")
    def test_access_token_expired_custom_threshold(self):
        integration = Integration.objects.create(
            team=self.team,
            kind="firebase",
            integration_id="proj",
            config={
                "project_id": "proj",
                "expires_in": 3600,
                "refreshed_at": int(time.time()) - 3500,
            },
            sensitive_config={"key_info": FAKE_KEY_INFO, "access_token": "token"},
        )
        wrapper = FirebaseIntegration(integration)

        # Not expired with a tight threshold
        assert wrapper.access_token_expired(time_threshold=timedelta(seconds=50)) is False
        # Expired with a generous threshold
        assert wrapper.access_token_expired(time_threshold=timedelta(seconds=3500)) is True

    @patch("posthog.models.integration.reload_integrations_on_workers")
    @patch("posthog.models.integration.GoogleRequest")
    @patch("posthog.models.integration.service_account.Credentials.from_service_account_info")
    def test_refresh_access_token(self, mock_from_sa, mock_google_request, mock_reload):
        integration = Integration.objects.create(
            team=self.team,
            kind="firebase",
            integration_id="proj",
            config={
                "project_id": "proj",
                "expires_in": 3600,
                "refreshed_at": int(time.time()) - 4000,
            },
            sensitive_config={"key_info": FAKE_KEY_INFO, "access_token": "old-token"},
        )
        wrapper = FirebaseIntegration(integration)

        new_creds = _mock_credentials(token="new-token", expiry_offset=3600)
        mock_from_sa.return_value = new_creds

        wrapper.refresh_access_token()

        integration.refresh_from_db()
        assert integration.sensitive_config["access_token"] == "new-token"
        mock_reload.assert_called_once_with(self.team.id, [integration.id])

    @patch("posthog.models.integration.reload_integrations_on_workers")
    @patch("posthog.models.integration.GoogleRequest")
    @patch("posthog.models.integration.service_account.Credentials.from_service_account_info")
    def test_get_access_token_refreshes_when_expired(self, mock_from_sa, mock_google_request, mock_reload):
        integration = Integration.objects.create(
            team=self.team,
            kind="firebase",
            integration_id="proj",
            config={
                "project_id": "proj",
                "expires_in": 3600,
                "refreshed_at": int(time.time()) - 4000,
            },
            sensitive_config={"key_info": FAKE_KEY_INFO, "access_token": "old-token"},
        )
        wrapper = FirebaseIntegration(integration)

        new_creds = _mock_credentials(token="refreshed-token", expiry_offset=3600)
        mock_from_sa.return_value = new_creds

        token = wrapper.get_access_token()
        assert token == "refreshed-token"

    def test_get_access_token_returns_cached_when_valid(self):
        integration = Integration.objects.create(
            team=self.team,
            kind="firebase",
            integration_id="proj",
            config={
                "project_id": "proj",
                "expires_in": 3600,
                "refreshed_at": int(time.time()),
            },
            sensitive_config={"key_info": FAKE_KEY_INFO, "access_token": "cached-token"},
        )
        wrapper = FirebaseIntegration(integration)

        token = wrapper.get_access_token()
        assert token == "cached-token"

    def test_clears_errors_on_upsert(self):
        integration = self._create_firebase_integration()
        integration.errors = "some previous error"
        integration.save()

        updated = self._create_firebase_integration()
        updated.refresh_from_db()
        assert updated.errors == ""
