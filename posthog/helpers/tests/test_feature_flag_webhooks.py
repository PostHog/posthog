import json
from freezegun import freeze_time
from django.conf import settings

from posthog.helpers.feature_flag_webhooks import create_feature_flag_webhook_payload, decrypt_webhook_headers
from posthog.models.feature_flag.feature_flag import FeatureFlag
from posthog.models.cohort import Cohort
from posthog.temporal.common.codec import EncryptionCodec
from posthog.test.base import BaseTest


class TestFeatureFlagWebhooks(BaseTest):
    def setUp(self):
        super().setUp()

    def test_create_webhook_payload_basic_flag(self):
        """Test webhook payload creation for a basic feature flag"""
        flag = FeatureFlag.objects.create(
            key="test-flag",
            name="Test Feature Flag",
            active=True,
            filters={"groups": [{"properties": [], "rollout_percentage": 50}]},
            team=self.team,
            created_by=self.user,
            rollout_percentage=50,
        )

        with freeze_time("2024-01-15T10:30:00Z"):
            payload = create_feature_flag_webhook_payload(flag, "created")

        assert payload["event"] == "feature_flag_changed"
        assert payload["change_type"] == "created"
        assert payload["timestamp"] == "2024-01-15T10:30:00+00:00"

        # Check feature flag data
        flag_data = payload["feature_flag"]
        assert flag_data["id"] == flag.id
        assert flag_data["key"] == "test-flag"
        assert flag_data["name"] == "Test Feature Flag"
        assert flag_data["active"] is True
        assert flag_data["deleted"] is False
        assert flag_data["filters"] == {"groups": [{"properties": [], "rollout_percentage": 50}]}
        assert flag_data["rollout_percentage"] == 50
        assert flag_data["version"] == 1
        assert flag_data["last_modified_by"] is None  # No modifications yet
        assert flag_data["is_remote_configuration"] is False
        assert flag_data["has_encrypted_payloads"] is False

        # Check team data
        team_data = payload["team"]
        assert team_data["id"] == self.team.id
        assert team_data["name"] == self.team.name
        assert team_data["organization_id"] == self.team.organization_id

        # Check metadata
        metadata = payload["metadata"]
        assert metadata["variants_count"] == 0
        assert metadata["conditions_count"] == 1
        assert metadata["uses_cohorts"] is False
        assert metadata["aggregation_group_type_index"] is None

    def test_create_webhook_payload_with_variants(self):
        """Test webhook payload creation for flag with variants"""
        flag = FeatureFlag.objects.create(
            key="variant-flag",
            name="Variant Test Flag",
            active=True,
            filters={
                "groups": [{"properties": [], "rollout_percentage": 100}],
                "multivariate": {
                    "variants": [
                        {"key": "control", "name": "Control", "rollout_percentage": 50},
                        {"key": "test", "name": "Test", "rollout_percentage": 50},
                    ]
                },
            },
            team=self.team,
            created_by=self.user,
        )

        payload = create_feature_flag_webhook_payload(flag, "updated")

        assert payload["change_type"] == "updated"
        metadata = payload["metadata"]
        assert metadata["variants_count"] == 2

    def test_create_webhook_payload_remote_config_with_payloads(self):
        """Test webhook payload creation for remote config flag with encrypted payloads"""
        remote_config_payload = {"config": {"theme": "dark", "timeout": 5000}}

        flag = FeatureFlag.objects.create(
            key="remote-config-flag",
            name="Remote Config Flag",
            active=True,
            filters={
                "groups": [{"properties": [], "rollout_percentage": 100}],
                "payloads": {"true": json.dumps(remote_config_payload)},
            },
            team=self.team,
            created_by=self.user,
            is_remote_configuration=True,
            has_encrypted_payloads=True,
        )

        payload = create_feature_flag_webhook_payload(flag, "updated")

        flag_data = payload["feature_flag"]
        assert flag_data["is_remote_configuration"] is True
        assert flag_data["has_encrypted_payloads"] is True

        # Should include the remote config payload
        assert "remote_config_payload" in payload
        assert payload["remote_config_payload"] == remote_config_payload

    def test_create_webhook_payload_remote_config_invalid_json(self):
        """Test webhook payload with invalid JSON in remote config"""
        flag = FeatureFlag.objects.create(
            key="invalid-json-flag",
            name="Invalid JSON Flag",
            active=True,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}], "payloads": {"true": "invalid-json{"}},
            team=self.team,
            created_by=self.user,
            is_remote_configuration=True,
            has_encrypted_payloads=True,
        )

        payload = create_feature_flag_webhook_payload(flag, "updated")

        # Should include the raw payload if JSON parsing fails
        assert "remote_config_payload" in payload
        assert payload["remote_config_payload"] == "invalid-json{"

    def test_create_webhook_payload_deleted_flag(self):
        """Test webhook payload creation for deleted flag"""
        flag = FeatureFlag.objects.create(
            key="deleted-flag",
            name="Deleted Flag",
            active=False,
            deleted=True,
            filters={"groups": []},
            team=self.team,
            created_by=self.user,
        )

        payload = create_feature_flag_webhook_payload(flag, "deleted")

        assert payload["change_type"] == "deleted"
        flag_data = payload["feature_flag"]
        assert flag_data["active"] is False
        assert flag_data["deleted"] is True

    def test_create_webhook_payload_with_user_modification(self):
        """Test webhook payload includes last modified user"""
        flag = FeatureFlag.objects.create(
            key="modified-flag",
            name="Modified Flag",
            active=True,
            filters={"groups": []},
            team=self.team,
            created_by=self.user,
            last_modified_by=self.user,
        )

        payload = create_feature_flag_webhook_payload(flag, "updated")

        flag_data = payload["feature_flag"]
        assert flag_data["last_modified_by"] == self.user.email

    def test_create_webhook_payload_with_cohorts(self):
        """Test webhook payload for flag using cohorts"""
        # Create a cohort first
        cohort = Cohort.objects.create(
            name="Test Cohort",
            team=self.team,
            groups=[{"properties": [{"key": "email", "value": "test@example.com", "type": "person"}]}],
        )

        flag = FeatureFlag.objects.create(
            key="cohort-flag",
            name="Cohort Flag",
            active=True,
            filters={
                "groups": [
                    {"properties": [{"key": "id", "value": cohort.id, "type": "cohort"}], "rollout_percentage": 100}
                ]
            },
            team=self.team,
            created_by=self.user,
        )

        payload = create_feature_flag_webhook_payload(flag, "created")

        metadata = payload["metadata"]
        assert metadata["uses_cohorts"] is True

    def test_create_webhook_payload_invalid_flag(self):
        """Test webhook payload creation with invalid flag object"""
        payload = create_feature_flag_webhook_payload(None, "created")
        assert payload == {}

        payload = create_feature_flag_webhook_payload("not-a-flag", "created")
        assert payload == {}

    def test_create_webhook_payload_comprehensive(self):
        """Test webhook payload creation with all possible fields populated"""
        flag = FeatureFlag.objects.create(
            key="comprehensive-flag",
            name="Comprehensive Test Flag",
            active=True,
            deleted=False,
            filters={
                "groups": [{"properties": [], "rollout_percentage": 30}, {"properties": [], "rollout_percentage": 70}],
                "multivariate": {
                    "variants": [
                        {"key": "variant-a", "name": "Variant A", "rollout_percentage": 33},
                        {"key": "variant-b", "name": "Variant B", "rollout_percentage": 33},
                        {"key": "variant-c", "name": "Variant C", "rollout_percentage": 34},
                    ]
                },
                "payloads": {"true": '{"feature": "enabled"}'},
            },
            team=self.team,
            created_by=self.user,
            last_modified_by=self.user,
            rollout_percentage=100,
            version=3,
            ensure_experience_continuity=True,
            has_enriched_analytics=True,
            is_remote_configuration=True,
            has_encrypted_payloads=True,
        )

        payload = create_feature_flag_webhook_payload(flag, "updated")

        # Verify all fields are correctly populated
        flag_data = payload["feature_flag"]
        assert flag_data["version"] == 3
        assert flag_data["ensure_experience_continuity"] is True
        assert flag_data["has_enriched_analytics"] is True
        assert flag_data["is_remote_configuration"] is True
        assert flag_data["has_encrypted_payloads"] is True

        metadata = payload["metadata"]
        assert metadata["variants_count"] == 3
        assert metadata["conditions_count"] == 2

        # Should include remote config payload
        assert "remote_config_payload" in payload
        assert payload["remote_config_payload"] == {"feature": "enabled"}

    def test_decrypt_webhook_headers_with_encrypted_values(self):
        """Test decryption of encrypted webhook headers"""
        codec = EncryptionCodec(settings)

        # Encrypt some header values
        encrypted_auth = codec.encrypt(b"Bearer secret123").decode("utf-8")
        encrypted_custom = codec.encrypt(b"custom-value").decode("utf-8")

        encrypted_headers = {
            "Authorization": encrypted_auth,
            "X-Custom-Header": encrypted_custom,
            "Content-Type": "application/json",  # Not encrypted
        }

        decrypted_headers = decrypt_webhook_headers(encrypted_headers)

        assert decrypted_headers["Authorization"] == "Bearer secret123"
        assert decrypted_headers["X-Custom-Header"] == "custom-value"
        assert decrypted_headers["Content-Type"] == "application/json"  # Unchanged

    def test_decrypt_webhook_headers_empty_or_none(self):
        """Test decryption with empty or None headers"""
        assert decrypt_webhook_headers(None) == {}
        assert decrypt_webhook_headers({}) == {}
        assert decrypt_webhook_headers("not-a-dict") == {}

    def test_decrypt_webhook_headers_non_string_values(self):
        """Test decryption with non-string header values"""
        headers = {
            "String-Header": "value",
            "Number-Header": 12345,
            "Boolean-Header": True,
        }

        decrypted_headers = decrypt_webhook_headers(headers)

        assert decrypted_headers["String-Header"] == "value"
        assert decrypted_headers["Number-Header"] == 12345
        assert decrypted_headers["Boolean-Header"] is True
