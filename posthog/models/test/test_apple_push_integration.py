from posthog.test.base import BaseTest

from parameterized import parameterized
from rest_framework.exceptions import ValidationError

from posthog.models.integration import ApplePushIntegration, Integration


class TestApplePushIntegration(BaseTest):
    def _create_apple_push_integration(
        self,
        signing_key: str = "-----BEGIN PRIVATE KEY-----\nfake-key\n-----END PRIVATE KEY-----",
        key_id: str = "ABC123KEY",
        team_id_apple: str = "TEAM123",
        bundle_id: str = "com.example.app",
        environment: str = "production",
        push_identity_verification: str | None = None,
    ) -> Integration:
        return ApplePushIntegration.integration_from_key(
            signing_key=signing_key,
            key_id=key_id,
            team_id_apple=team_id_apple,
            bundle_id=bundle_id,
            team_id=self.team.id,
            environment=environment,
            push_identity_verification=push_identity_verification,
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

    def test_reconnecting_preserves_identity_verification(self):
        # Rotating the .p8 signing key is a routine action that re-upserts the integration. It must
        # not silently reset the verification policy, which would reopen device takeover.
        self._create_apple_push_integration(push_identity_verification="required")
        reconnected = self._create_apple_push_integration(key_id="ROTATED_KEY")

        assert reconnected.config["push_identity_verification"] == "required"

    def test_rejects_an_unknown_identity_verification_mode(self):
        with self.assertRaises(ValidationError):
            self._create_apple_push_integration(push_identity_verification="enabled")

    def test_separate_integrations_for_different_bundles(self):
        first = self._create_apple_push_integration(bundle_id="com.example.app1")
        second = self._create_apple_push_integration(bundle_id="com.example.app2")

        assert first.id != second.id

    @parameterized.expand(
        [
            (f"{field}_{'blank' if not value else 'whitespace'}", field, value)
            for field in ("signing_key", "key_id", "team_id_apple", "bundle_id")
            for value in ("", "   ")
        ]
    )
    def test_validates_required_fields(self, _name, field, value):
        with self.assertRaises(ValidationError):
            self._create_apple_push_integration(**{field: value})

    def test_strips_whitespace_around_the_signing_key(self):
        # A leading space makes the key unusable for ES256, so the credential could never send.
        integration = self._create_apple_push_integration(
            signing_key="  -----BEGIN PRIVATE KEY-----\nfake-key\n-----END PRIVATE KEY-----  "
        )

        assert integration.sensitive_config["signing_key"] == (
            "-----BEGIN PRIVATE KEY-----\nfake-key\n-----END PRIVATE KEY-----"
        )

    def test_strips_whitespace_around_the_identifiers(self):
        integration = self._create_apple_push_integration()
        spaced = self._create_apple_push_integration(
            team_id_apple=" TEAM123", bundle_id="com.example.app\n", key_id="ABC123KEY "
        )

        assert spaced.id == integration.id
        assert spaced.integration_id == "TEAM123.com.example.app"
        assert spaced.config["team_id"] == "TEAM123"
        assert spaced.config["bundle_id"] == "com.example.app"
        assert spaced.config["key_id"] == "ABC123KEY"

    def test_sandbox_and_production_credentials_coexist(self):
        production = self._create_apple_push_integration()
        sandbox = self._create_apple_push_integration(environment="sandbox")

        assert production.id != sandbox.id
        assert production.integration_id == "TEAM123.com.example.app"
        assert sandbox.integration_id == "TEAM123.com.example.app:sandbox"
        production.refresh_from_db()
        assert production.config["environment"] == "production"
        assert sandbox.config["environment"] == "sandbox"

    def test_a_bundle_id_cannot_impersonate_a_sandbox_credential(self):
        sandbox = self._create_apple_push_integration(environment="sandbox")
        lookalike = self._create_apple_push_integration(bundle_id="com.example.app.sandbox")

        assert sandbox.id != lookalike.id

    @parameterized.expand(
        [
            ("colon_in_team_id", {"team_id_apple": "TEAM:123"}),
            ("colon_in_bundle_id", {"bundle_id": "com.example.app:sandbox"}),
            # "TEAM.123" + "com.example.app" would read as "TEAM" + "123.com.example.app".
            ("period_in_team_id", {"team_id_apple": "TEAM.123"}),
        ]
    )
    def test_rejects_an_identifier_that_could_forge_another_identity(self, _name, kwargs):
        with self.assertRaises(ValidationError):
            self._create_apple_push_integration(**kwargs)

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

    @parameterized.expand(
        [
            ("production", "com.example.app"),
            ("sandbox", "com.example.app (sandbox)"),
        ]
    )
    def test_display_name(self, environment, expected):
        integration = self._create_apple_push_integration(environment=environment)
        assert integration.display_name == expected

    def test_clears_errors_on_upsert(self):
        integration = self._create_apple_push_integration()
        integration.errors = "some previous error"
        integration.save()

        updated = self._create_apple_push_integration()
        updated.refresh_from_db()
        assert updated.errors == ""
