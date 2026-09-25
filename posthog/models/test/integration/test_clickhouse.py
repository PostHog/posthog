from typing import cast

import pytest
from posthog.test.base import BaseTest

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from posthog.helpers.encrypted_fields import EncryptedJSONField
from posthog.models.integration import ClickHouseIntegration, Integration, IntegrationError


class TestClickHouseIntegrationFromConfig(BaseTest):
    def test_keeps_the_password_out_of_the_visible_config(self) -> None:
        integration = ClickHouseIntegration.integration_from_config(
            team_id=self.team.pk, host="ch.example.com", user="exporter", password="hunter2", name="Analytics"
        )

        assert "password" not in integration.config
        assert ClickHouseIntegration(integration).password == "hunter2"
        assert integration.display_name == "Analytics"

    def test_reads_a_password_that_was_encrypted_twice(self) -> None:
        integration = ClickHouseIntegration.integration_from_config(
            team_id=self.team.pk, host="ch.example.com", user="exporter", password="hunter2"
        )
        field = cast(EncryptedJSONField, Integration._meta.get_field("sensitive_config"))  # type: ignore[misc]
        integration.sensitive_config = {"password": field.encrypt("hunter2")}
        integration.save(update_fields=["sensitive_config"])
        integration.refresh_from_db()

        assert ClickHouseIntegration(integration).password == "hunter2"


class TestClickHouseIntegrationValidation(SimpleTestCase):
    @parameterized.expand(
        [
            ("missing_host", {"user": "exporter", "password": "hunter2"}),
            ("missing_password", {"host": "ch.example.com", "user": "exporter"}),
            ("port_out_of_range", {"host": "ch.example.com", "port": 70000, "user": "exporter", "password": "hunter2"}),
            (
                "verify_as_a_string",
                {"host": "ch.example.com", "user": "exporter", "password": "hunter2", "verify": "false"},
            ),
        ]
    )
    def test_rejects_an_incomplete_config(self, _name: str, config: dict) -> None:
        with pytest.raises(IntegrationError):
            ClickHouseIntegration.integration_from_config(team_id=1, **config)

    @override_settings(FORCE_URL_VALIDATION=True)
    def test_rejects_an_internal_host(self) -> None:
        with pytest.raises(IntegrationError):
            ClickHouseIntegration.integration_from_config(
                team_id=1, host="127.0.0.1", user="exporter", password="hunter2"
            )
