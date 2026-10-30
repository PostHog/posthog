"""Tests for the Databricks integration."""

import pytest
from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.models.integration import DatabricksIntegration, DatabricksIntegrationError
from posthog.models.integration.databricks import is_databricks_workspace_host


@pytest.mark.parametrize(
    "host,expected",
    [
        ("dbc-a1b2c3d4-e5f6.cloud.databricks.com", True),
        ("dbc-a1b2c3d4-e5f6.cloud.databricks.us", True),
        ("adb-1234567890123456.7.azuredatabricks.net", True),
        ("adb-1234567890123456.7.databricks.azure.us", True),
        ("adb-1234567890123456.7.databricks.azure.cn", True),
        ("1234567890123456.7.gcp.databricks.com", True),
        ("DBC-A1B2C3D4-E5F6.Cloud.Databricks.com", True),
        ("dbc-a1b2c3d4-e5f6.cloud.databricks.com.", False),
        ("databricks.com", False),
        ("cloud.databricks.com", False),
        ("evil.example.com", False),
        ("evilcloud.databricks.com", False),
        ("x.cloud.databricks.com.evil.com", False),
        ("evil.com#.cloud.databricks.com", False),
        ("evil.com/.cloud.databricks.com", False),
        ("user@x.cloud.databricks.com", False),
        ("x.cloud.databricks.com:8443", False),
        ("https://x.cloud.databricks.com", False),
        ("10.0.0.1", False),
        ("", False),
    ],
)
def test_is_databricks_workspace_host(host: str, expected: bool) -> None:
    assert is_databricks_workspace_host(host) is expected


class TestDatabricksIntegrationModel(BaseTest):
    @parameterized.expand(
        [
            ("dbc-a1b2c3d4-e5f6.cloud.databricks.com", "dbc-a1b2c3d4-e5f6.cloud.databricks.com"),
            ("httpteam.cloud.databricks.com", "httpteam.cloud.databricks.com"),
            ("DBC-A1B2C3D4-E5F6.Cloud.Databricks.com", "dbc-a1b2c3d4-e5f6.cloud.databricks.com"),
        ]
    )
    @patch("posthog.models.integration.databricks.is_url_allowed", return_value=(True, None))
    def test_integration_from_config_with_valid_config(self, server_hostname, expected_hostname, mock_is_url_allowed):
        integration = DatabricksIntegration.integration_from_config(
            team_id=self.team.pk,
            server_hostname=server_hostname,
            client_id="client_id",
            client_secret="client_secret",
            created_by=self.user,
        )
        assert integration.team == self.team
        assert integration.created_by == self.user
        assert integration.config == {"server_hostname": expected_hostname}
        assert integration.integration_id == expected_hostname
        assert integration.sensitive_config == {"client_id": "client_id", "client_secret": "client_secret"}

    @patch("posthog.models.integration.databricks.is_url_allowed", return_value=(False, "Could not resolve host"))
    def test_integration_from_config_with_invalid_server_hostname(self, mock_is_url_allowed):
        with pytest.raises(
            DatabricksIntegrationError,
            match="Databricks integration error: could not validate hostname 'dbc-missing.cloud.databricks.com'",
        ):
            DatabricksIntegration.integration_from_config(
                team_id=self.team.pk,
                server_hostname="dbc-missing.cloud.databricks.com",
                client_id="client_id",
                client_secret="client_secret",
                created_by=self.user,
            )
