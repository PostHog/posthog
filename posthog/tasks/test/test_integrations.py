import time
from typing import Optional

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from posthog.models.integration import (
    ERROR_TOKEN_REFRESH_FAILED,
    INTERCOM_TOKEN_VALIDATION_INTERVAL_SECONDS,
    Integration,
)
from posthog.tasks.integrations import refresh_integrations, validate_intercom_integration


class TestIntegrationsTasks(APIBaseTest):
    integrations: list[Integration] = []

    def setUp(self) -> None:
        super().setUp()

    def create_integration(
        self, kind: str, config: Optional[dict] = None, sensitive_config: Optional[dict] = None
    ) -> Integration:
        _config = {"refreshed_at": int(time.time()), "expires_in": 3600}
        _sensitive_config = {"refresh_token": "REFRESH"}
        _config.update(config or {})
        _sensitive_config.update(sensitive_config or {})

        return Integration.objects.create(team=self.team, kind=kind, config=_config, sensitive_config=_sensitive_config)

    def test_refresh_integrations_schedules_refreshes_for_expired(self) -> None:
        _integration_1 = self.create_integration("other")  # not an oauth one
        _integration_2 = self.create_integration("slack")  # not expired
        integration_3 = self.create_integration("slack", config={"refreshed_at": time.time() - 3600})  # expired
        integration_4 = self.create_integration(
            "slack", config={"refreshed_at": time.time() - 3600 + 170}
        )  # expired with buffer

        with patch("posthog.tasks.integrations.refresh_integration.delay") as refresh_integration_mock:
            refresh_integrations()
            # Both 3 and 4 should be refreshed
            assert refresh_integration_mock.call_args_list == [((integration_3.id,),), ((integration_4.id,),)]

    def test_refresh_integrations_schedules_intercom_validation_when_due(self) -> None:
        # Never-validated and stale integrations should be enqueued; the recently-validated one should not.
        integration_never = Integration.objects.create(
            team=self.team,
            kind="intercom",
            config={"app.region": "US"},
            sensitive_config={"access_token": "TOKEN_1"},
        )
        integration_stale = Integration.objects.create(
            team=self.team,
            kind="intercom",
            config={
                "app.region": "Europe",
                "validated_at": int(time.time()) - INTERCOM_TOKEN_VALIDATION_INTERVAL_SECONDS - 60,
            },
            sensitive_config={"access_token": "TOKEN_2"},
        )
        _integration_fresh = Integration.objects.create(
            team=self.team,
            kind="intercom",
            config={"app.region": "US", "validated_at": int(time.time())},
            sensitive_config={"access_token": "TOKEN_3"},
        )

        with patch("posthog.tasks.integrations.validate_intercom_integration.delay") as validate_mock:
            refresh_integrations()
            scheduled_ids = sorted(call.args[0] for call in validate_mock.call_args_list)
            assert scheduled_ids == sorted([integration_never.id, integration_stale.id])

    @patch("posthog.models.integration.requests.get")
    def test_validate_intercom_integration_marks_errors_on_401(self, mock_get) -> None:
        mock_get.return_value.status_code = 401
        integration = Integration.objects.create(
            team=self.team,
            kind="intercom",
            config={"app.region": "US"},
            sensitive_config={"access_token": "TOKEN"},
        )

        validate_intercom_integration(integration.id)

        integration.refresh_from_db()
        assert integration.errors == ERROR_TOKEN_REFRESH_FAILED

    @patch("posthog.models.integration.requests.get")
    def test_validate_intercom_integration_noop_for_wrong_kind(self, mock_get) -> None:
        integration = self.create_integration("slack")
        validate_intercom_integration(integration.id)
        mock_get.assert_not_called()
