from posthog.test.base import BaseTest

from rest_framework.exceptions import ValidationError

from posthog.models.integration import ApplePushIntegration, Integration


class TestApplePushIntegration(BaseTest):
    def _create_apple_push_integration(
        self,
        signing_key: str = "-----BEGIN PRIVATE KEY-----\nfake-key\n-----END PRIVATE KEY-----",
        key_id: str = "ABC123KEY",
        team_id_apple: str = "TEAM123",
        bundle_id: str = "com.example.app",
    ) -> Integration:
        return ApplePushIntegration.integration_from_key(
            signing_key=signing_key,
            key_id=key_id,
            team_id_apple=team_id_apple,
            bundle_id=bundle_id,
            team_id=self.team.id,
        )

    def test_creates_integration(self):
        integration = self._create_apple_push_integration()

        assert integration.kind == "apns"
        assert integration.integration_id == "TEAM123.com.example.app"
        assert integration.config["team_id"] == "TEAM123"
        assert integration.config["bundle_id"] == "com.example.app"
        assert integration.config["key_id"] == "ABC123KEY"
        assert integration.sensitive_config["signing_key"].startswith("-----BEGIN PRIVATE KEY-----")

    def test_upserts_on_same_team_and_bundle(self):
        first = self._create_apple_push_integration()
        second = self._create_apple_push_integration(key_id="NEW_KEY_ID")

        assert first.id == second.id
        second.refresh_from_db()
        assert second.config["key_id"] == "NEW_KEY_ID"

    def test_separate_integrations_for_different_bundles(self):
        first = self._create_apple_push_integration(bundle_id="com.example.app1")
        second = self._create_apple_push_integration(bundle_id="com.example.app2")

        assert first.id != second.id

    def test_validates_required_fields(self):
        with self.assertRaises(ValidationError):
            self._create_apple_push_integration(signing_key="")

        with self.assertRaises(ValidationError):
            self._create_apple_push_integration(key_id="")

        with self.assertRaises(ValidationError):
            self._create_apple_push_integration(team_id_apple="")

        with self.assertRaises(ValidationError):
            self._create_apple_push_integration(bundle_id="")

    def test_wrapper_properties(self):
        integration = self._create_apple_push_integration()
        wrapper = ApplePushIntegration(integration)

        assert wrapper.team_id_apple == "TEAM123"
        assert wrapper.bundle_id == "com.example.app"
        assert wrapper.key_id == "ABC123KEY"
        assert wrapper.signing_key.startswith("-----BEGIN PRIVATE KEY-----")

    def test_wrapper_rejects_wrong_kind(self):
        integration = Integration.objects.create(
            team=self.team,
            kind="slack",
            config={},
            sensitive_config={},
        )

        with self.assertRaisesMessage(Exception, "ApplePushIntegration init called with Integration with wrong 'kind'"):
            ApplePushIntegration(integration)

    def test_display_name(self):
        integration = self._create_apple_push_integration()
        assert integration.display_name == "com.example.app"

    def test_clears_errors_on_upsert(self):
        integration = self._create_apple_push_integration()
        integration.errors = "some previous error"
        integration.save()

        updated = self._create_apple_push_integration()
        updated.refresh_from_db()
        assert updated.errors == ""
