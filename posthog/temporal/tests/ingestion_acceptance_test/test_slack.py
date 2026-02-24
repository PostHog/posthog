import pytest
from unittest.mock import MagicMock, patch

from posthog.temporal.ingestion_acceptance_test.config import Config
from posthog.temporal.ingestion_acceptance_test.results import TestResult, TestSuiteResult
from posthog.temporal.ingestion_acceptance_test.slack import send_slack_notification


@pytest.fixture
def config() -> Config:
    return Config(
        api_host="https://test.posthog.com",
        project_api_key="phc_test_key",
        project_id="12345",
        personal_api_key="phx_personal_key",
        slack_webhook_url="https://hooks.slack.com/services/T00/B00/XXX",
    )


@pytest.fixture
def passing_result() -> TestSuiteResult:
    return TestSuiteResult(
        results=[
            TestResult(
                test_name="test_one",
                test_file="test_file.py",
                status="passed",
                duration_seconds=1.5,
                timestamp="2024-01-01T00:00:00Z",
            ),
            TestResult(
                test_name="test_two",
                test_file="test_file.py",
                status="passed",
                duration_seconds=2.0,
                timestamp="2024-01-01T00:00:00Z",
            ),
        ],
        total_duration_seconds=3.5,
        environment={"api_host": "https://test.posthog.com", "project_id": "12345"},
        timestamp="2024-01-01T00:00:00Z",
    )


@pytest.fixture
def failing_result() -> TestSuiteResult:
    return TestSuiteResult(
        results=[
            TestResult(
                test_name="test_passing",
                test_file="test_file.py",
                status="passed",
                duration_seconds=1.0,
                timestamp="2024-01-01T00:00:00Z",
            ),
            TestResult(
                test_name="test_failing",
                test_file="test_file.py",
                status="failed",
                duration_seconds=2.0,
                timestamp="2024-01-01T00:00:00Z",
                error_message="AssertionError: expected 1, got 2",
            ),
        ],
        total_duration_seconds=3.0,
        environment={"api_host": "https://test.posthog.com", "project_id": "12345"},
        timestamp="2024-01-01T00:00:00Z",
    )


class TestSendSlackNotification:
    @patch("posthog.temporal.ingestion_acceptance_test.slack.requests.post")
    def test_skips_notification_on_success(
        self, mock_post: MagicMock, config: Config, passing_result: TestSuiteResult
    ) -> None:
        result = send_slack_notification(config, passing_result)

        assert result is True
        mock_post.assert_not_called()

    @patch("posthog.temporal.ingestion_acceptance_test.slack.requests.post")
    def test_posts_to_webhook_url_on_failure(
        self, mock_post: MagicMock, config: Config, failing_result: TestSuiteResult
    ) -> None:
        mock_post.return_value.raise_for_status = MagicMock()

        send_slack_notification(config, failing_result)

        mock_post.assert_called_once()
        url = mock_post.call_args[0][0]
        assert url == "https://hooks.slack.com/services/T00/B00/XXX"

    @patch("posthog.temporal.ingestion_acceptance_test.slack.requests.post")
    def test_sends_json_payload(self, mock_post: MagicMock, config: Config, failing_result: TestSuiteResult) -> None:
        mock_post.return_value.raise_for_status = MagicMock()

        send_slack_notification(config, failing_result)

        call_kwargs = mock_post.call_args[1]
        assert "json" in call_kwargs
        assert "blocks" in call_kwargs["json"]

    @patch("posthog.temporal.ingestion_acceptance_test.slack.requests.post")
    def test_failing_payload_contains_failure_header(
        self, mock_post: MagicMock, config: Config, failing_result: TestSuiteResult
    ) -> None:
        mock_post.return_value.raise_for_status = MagicMock()

        send_slack_notification(config, failing_result)

        payload = mock_post.call_args[1]["json"]
        blocks = payload["blocks"]

        header_block = blocks[0]
        assert header_block["type"] == "section"
        header_text = header_block["text"]["text"]
        assert "Unsuccessful" in header_text

    @patch("posthog.temporal.ingestion_acceptance_test.slack.requests.post")
    def test_payload_contains_summary_with_counts(
        self, mock_post: MagicMock, config: Config, failing_result: TestSuiteResult
    ) -> None:
        mock_post.return_value.raise_for_status = MagicMock()

        send_slack_notification(config, failing_result)

        payload = mock_post.call_args[1]["json"]
        blocks = payload["blocks"]

        summary_block = blocks[1]
        assert summary_block["type"] == "context"
        summary_text = summary_block["elements"][0]["text"]

        assert "Passed: 1" in summary_text
        assert "Failed" in summary_text

    @patch("posthog.temporal.ingestion_acceptance_test.slack.requests.post")
    def test_payload_contains_environment_info(
        self, mock_post: MagicMock, config: Config, failing_result: TestSuiteResult
    ) -> None:
        mock_post.return_value.raise_for_status = MagicMock()

        send_slack_notification(config, failing_result)

        payload = mock_post.call_args[1]["json"]
        blocks = payload["blocks"]

        env_block = blocks[-1]
        assert env_block["type"] == "context"
        env_text = env_block["elements"][0]["text"]

        assert "test.posthog.com" in env_text
        assert "12345" in env_text

    @patch("posthog.temporal.ingestion_acceptance_test.slack.requests.post")
    def test_failing_payload_contains_error_message(
        self, mock_post: MagicMock, config: Config, failing_result: TestSuiteResult
    ) -> None:
        mock_post.return_value.raise_for_status = MagicMock()

        send_slack_notification(config, failing_result)

        payload = mock_post.call_args[1]["json"]
        blocks = payload["blocks"]

        context_blocks = [b for b in blocks if b.get("type") == "context"]
        all_text = " ".join(str(b) for b in context_blocks)

        assert "test_failing" in all_text
        assert "AssertionError" in all_text

    @patch("posthog.temporal.ingestion_acceptance_test.slack.requests.post")
    def test_does_nothing_when_no_webhook_url(self, mock_post: MagicMock, failing_result: TestSuiteResult) -> None:
        config_no_webhook = Config(
            api_host="https://test.posthog.com",
            project_api_key="phc_test_key",
            project_id="12345",
            personal_api_key="phx_personal_key",
            slack_webhook_url=None,
        )

        send_slack_notification(config_no_webhook, failing_result)

        mock_post.assert_not_called()
