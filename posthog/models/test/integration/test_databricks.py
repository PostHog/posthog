"""Tests for the Databricks integration."""

import pytest
from posthog.test.base import BaseTest
from unittest.mock import patch

from posthog.models.integration import DatabricksIntegration, DatabricksIntegrationError


class TestDatabricksIntegrationModel(BaseTest):
    @patch("posthog.models.integration.databricks.is_url_allowed", return_value=(True, None))
    def test_integration_from_config_with_valid_config(self, mock_is_url_allowed):
        integration = DatabricksIntegration.integration_from_config(
            team_id=self.team.pk,
            server_hostname="databricks.com",
            client_id="client_id",
            client_secret="client_secret",
            created_by=self.user,
        )
        assert integration.team == self.team
        assert integration.created_by == self.user
        assert integration.config == {"server_hostname": "databricks.com"}
        assert integration.sensitive_config == {"client_id": "client_id", "client_secret": "client_secret"}

    @patch("posthog.models.integration.databricks.is_url_allowed", return_value=(False, "Could not resolve host"))
    def test_integration_from_config_with_invalid_server_hostname(self, mock_is_url_allowed):
        with pytest.raises(
            DatabricksIntegrationError, match="Databricks integration error: could not validate hostname 'invalid'"
        ):
            DatabricksIntegration.integration_from_config(
                team_id=self.team.pk,
                server_hostname="invalid",
                client_id="client_id",
                client_secret="client_secret",
                created_by=self.user,
            )
