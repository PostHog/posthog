"""Tests for the Snowflake integration."""

import pytest
from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.models.integration import Integration, SnowflakeIntegration, SnowflakeIntegrationError


class TestSnowflakeIntegrationModel(BaseTest):
    def test_integration_from_config_with_password_auth(self):
        integration = SnowflakeIntegration.integration_from_config(
            team_id=self.team.pk,
            name="prod-snowflake",
            account="myorg-myaccount",
            user="posthog_svc",
            authentication_type="password",
            password="secret",
            created_by=self.user,
        )
        assert integration.kind == Integration.IntegrationKind.SNOWFLAKE
        # The identifier is the user-supplied name, never a credential.
        assert integration.integration_id == "prod-snowflake"
        # account, user and authentication_type are non-sensitive and live in config.
        assert integration.config == {
            "name": "prod-snowflake",
            "account": "myorg-myaccount",
            "user": "posthog_svc",
            "authentication_type": "password",
        }
        assert integration.sensitive_config == {"password": "secret"}
        wrapped = SnowflakeIntegration(integration)
        assert wrapped.password == "secret"
        assert wrapped.private_key is None
        # display_name surfaces auth type and account so users can tell integrations apart.
        assert integration.display_name == "prod-snowflake (account: myorg-myaccount, password auth)"

    def test_integration_from_config_with_keypair_auth(self):
        integration = SnowflakeIntegration.integration_from_config(
            team_id=self.team.pk,
            name="prod-snowflake",
            account="myorg-myaccount",
            user="posthog_svc",
            authentication_type="keypair",
            private_key="-----BEGIN PRIVATE KEY-----\nxxx\n-----END PRIVATE KEY-----",
            private_key_passphrase="phrase",
            created_by=self.user,
        )
        assert integration.config["authentication_type"] == "keypair"
        assert integration.sensitive_config == {
            "private_key": "-----BEGIN PRIVATE KEY-----\nxxx\n-----END PRIVATE KEY-----",
            "private_key_passphrase": "phrase",
        }
        # A password from a switched auth mode must never linger alongside the key-pair material.
        assert "password" not in integration.sensitive_config
        wrapped = SnowflakeIntegration(integration)
        assert wrapped.private_key == "-----BEGIN PRIVATE KEY-----\nxxx\n-----END PRIVATE KEY-----"
        assert wrapped.private_key_passphrase == "phrase"

    def test_integration_from_config_keypair_without_passphrase(self):
        integration = SnowflakeIntegration.integration_from_config(
            team_id=self.team.pk,
            name="prod-snowflake",
            account="myorg-myaccount",
            user="posthog_svc",
            authentication_type="keypair",
            private_key="-----BEGIN PRIVATE KEY-----\nxxx\n-----END PRIVATE KEY-----",
        )
        assert integration.sensitive_config == {
            "private_key": "-----BEGIN PRIVATE KEY-----\nxxx\n-----END PRIVATE KEY-----"
        }

    @parameterized.expand(
        [
            ("missing_name", "", "myorg-myaccount", "posthog_svc"),
            ("missing_account", "prod-snowflake", "", "posthog_svc"),
            ("missing_user", "prod-snowflake", "myorg-myaccount", ""),
        ]
    )
    def test_integration_from_config_requires_name_account_user(self, _name, name, account, user):
        with pytest.raises(SnowflakeIntegrationError, match="Name, account, and user must be provided"):
            SnowflakeIntegration.integration_from_config(
                team_id=self.team.pk,
                name=name,
                account=account,
                user=user,
                authentication_type="password",
                password="secret",
            )

    @parameterized.expand(
        [
            ("password_missing_password", "password", {}, "Password is required"),
            ("keypair_missing_private_key", "keypair", {}, "Private key is required"),
            ("invalid_auth_type", "oauth", {"password": "secret"}, "Invalid authentication type: oauth"),
        ]
    )
    def test_integration_from_config_rejects_invalid_auth(self, _name, authentication_type, credentials, expected):
        with pytest.raises(SnowflakeIntegrationError, match=expected):
            SnowflakeIntegration.integration_from_config(
                team_id=self.team.pk,
                name="prod-snowflake",
                account="myorg-myaccount",
                user="posthog_svc",
                authentication_type=authentication_type,
                **credentials,
            )

    def test_integration_from_config_rejects_duplicate_name(self):
        SnowflakeIntegration.integration_from_config(
            team_id=self.team.pk,
            name="prod-snowflake",
            account="myorg-myaccount",
            user="posthog_svc",
            authentication_type="password",
            password="secret",
        )
        with pytest.raises(SnowflakeIntegrationError, match="An integration named 'prod-snowflake' already exists"):
            SnowflakeIntegration.integration_from_config(
                team_id=self.team.pk,
                name="prod-snowflake",
                account="other-account",
                user="other_user",
                authentication_type="password",
                password="other-secret",
            )
        assert Integration.objects.filter(team=self.team, integration_id="prod-snowflake").count() == 1

    @parameterized.expand(
        [
            ("simple", "myaccount"),
            ("org_account", "myorg-myaccount"),
            ("legacy_locator", "xy12345.us-east-1.aws"),
        ]
    )
    def test_validate_account_accepts_valid_identifiers(self, _name, account):
        SnowflakeIntegration.validate_account(account)  # must not raise

    @parameterized.expand(
        [
            ("full_url", "https://myaccount.snowflakecomputing.com"),
            ("with_path", "myaccount/foo"),
            ("with_at", "user@myaccount"),
            ("with_colon", "myaccount:443"),
            ("with_fragment", "myaccount#"),
            ("with_whitespace", "my account"),
            ("empty", ""),
        ]
    )
    def test_validate_account_rejects_malformed_identifiers(self, _name, account):
        with pytest.raises(SnowflakeIntegrationError, match="invalid account identifier"):
            SnowflakeIntegration.validate_account(account)

    def test_wrapping_wrong_kind_raises(self):
        integration = Integration.objects.create(
            team=self.team, kind=Integration.IntegrationKind.AWS_S3, integration_id="x"
        )
        with pytest.raises(SnowflakeIntegrationError, match="is not a Snowflake integration"):
            SnowflakeIntegration(integration)

    def test_wrapping_missing_config_raises(self):
        integration = Integration.objects.create(
            team=self.team, kind=Integration.IntegrationKind.SNOWFLAKE, integration_id="x", config={}
        )
        with pytest.raises(SnowflakeIntegrationError, match="missing"):
            SnowflakeIntegration(integration)
