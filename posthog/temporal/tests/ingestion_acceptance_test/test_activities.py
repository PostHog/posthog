import time
import asyncio

import pytest
from unittest.mock import MagicMock, patch

from posthog.temporal.ingestion_acceptance_test.config import Config


@pytest.fixture
def config() -> Config:
    return Config(
        api_host="https://test.posthog.com",
        project_api_key="phc_test_key",
        project_id="12345",
        personal_api_key="phx_personal_key",
        slack_webhook_url="https://hooks.slack.com/services/T00/B00/XXX",
        activity_timeout_seconds=1,
    )


class TestRunIngestionAcceptanceTestsTimeout:
    @patch("posthog.temporal.ingestion_acceptance_test.activities.send_slack_timeout_notification")
    @patch("posthog.temporal.ingestion_acceptance_test.activities.send_slack_notification")
    @patch("posthog.temporal.ingestion_acceptance_test.activities.PostHogClient")
    @patch("posthog.temporal.ingestion_acceptance_test.activities.posthoganalytics.Posthog")
    @patch("posthog.temporal.ingestion_acceptance_test.activities.discover_tests", return_value=[])
    @patch("posthog.temporal.ingestion_acceptance_test.activities.Config")
    @patch("posthog.temporal.ingestion_acceptance_test.activities.run_tests")
    @pytest.mark.asyncio
    async def test_sends_slack_timeout_notification_on_timeout(
        self,
        mock_run_tests: MagicMock,
        mock_config_cls: MagicMock,
        mock_discover: MagicMock,
        mock_posthog: MagicMock,
        mock_client_cls: MagicMock,
        mock_send_slack: MagicMock,
        mock_send_timeout: MagicMock,
        config: Config,
    ) -> None:
        mock_config_cls.return_value = config

        def slow_run_tests(*args, **kwargs):
            time.sleep(5)

        mock_run_tests.side_effect = slow_run_tests

        from posthog.temporal.ingestion_acceptance_test.activities import run_ingestion_acceptance_tests

        with pytest.raises(asyncio.TimeoutError):
            await run_ingestion_acceptance_tests()

        mock_send_timeout.assert_called_once_with(config)
        mock_send_slack.assert_not_called()

    @patch("posthog.temporal.ingestion_acceptance_test.activities.send_slack_timeout_notification")
    @patch("posthog.temporal.ingestion_acceptance_test.activities.send_slack_notification")
    @patch("posthog.temporal.ingestion_acceptance_test.activities.PostHogClient")
    @patch("posthog.temporal.ingestion_acceptance_test.activities.posthoganalytics.Posthog")
    @patch("posthog.temporal.ingestion_acceptance_test.activities.discover_tests", return_value=[])
    @patch("posthog.temporal.ingestion_acceptance_test.activities.Config")
    @patch("posthog.temporal.ingestion_acceptance_test.activities.run_tests")
    @pytest.mark.asyncio
    async def test_does_not_send_timeout_notification_when_tests_complete(
        self,
        mock_run_tests: MagicMock,
        mock_config_cls: MagicMock,
        mock_discover: MagicMock,
        mock_posthog: MagicMock,
        mock_client_cls: MagicMock,
        mock_send_slack: MagicMock,
        mock_send_timeout: MagicMock,
        config: Config,
    ) -> None:
        mock_config_cls.return_value = config

        mock_result = MagicMock()
        mock_result.to_dict.return_value = {"success": True}
        mock_run_tests.return_value = mock_result

        from posthog.temporal.ingestion_acceptance_test.activities import run_ingestion_acceptance_tests

        result = await run_ingestion_acceptance_tests()

        assert result == {"success": True}
        mock_send_timeout.assert_not_called()
        mock_send_slack.assert_called_once()
