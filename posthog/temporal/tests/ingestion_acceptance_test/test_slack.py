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
    def test_posts_to_webhook_url(self, mock_post: MagicMock, config: Config, passing_result: TestSuiteResult) -> None:
        mock_post.return_value.raise_for_status = MagicMock()

        send_slack_notification(config, passing_result)

        mock_post.assert_called_once()
        url = mock_post.call_args[0][0]
        assert url == "https://hooks.slack.com/services/T00/B00/XXX"

    @patch("posthog.temporal.ingestion_acceptance_test.slack.requests.post")
    def test_sends_json_payload(self, mock_post: MagicMock, config: Config, passing_result: TestSuiteResult) -> None:
        mock_post.return_value.raise_for_status = MagicMock()

        send_slack_notification(config, passing_result)

        call_kwargs = mock_post.call_args[1]
        assert "json" in call_kwargs
        assert "blocks" in call_kwargs["json"]

    @patch("posthog.temporal.ingestion_acceptance_test.slack.requests.post")
    def test_passing_payload_contains_success_header(
        self, mock_post: MagicMock, config: Config, passing_result: TestSuiteResult
    ) -> None:
        mock_post.return_value.raise_for_status = MagicMock()

        send_slack_notification(config, passing_result)

        payload = mock_post.call_args[1]["json"]
        blocks = payload["blocks"]

        header_block = next(b for b in blocks if b.get("type") == "header")
        header_text = header_block["text"]["text"]
        assert "Passed" in header_text

    @patch("posthog.temporal.ingestion_acceptance_test.slack.requests.post")
    def test_failing_payload_contains_failure_header(
        self, mock_post: MagicMock, config: Config, failing_result: TestSuiteResult
    ) -> None:
        mock_post.return_value.raise_for_status = MagicMock()

        send_slack_notification(config, failing_result)

        payload = mock_post.call_args[1]["json"]
        blocks = payload["blocks"]

        header_block = next(b for b in blocks if b.get("type") == "header")
        header_text = header_block["text"]["text"]
        assert "Failed" in header_text

    @patch("posthog.temporal.ingestion_acceptance_test.slack.requests.post")
    def test_payload_contains_summary_with_counts(
        self, mock_post: MagicMock, config: Config, failing_result: TestSuiteResult
    ) -> None:
        mock_post.return_value.raise_for_status = MagicMock()

        send_slack_notification(config, failing_result)

        payload = mock_post.call_args[1]["json"]
        blocks = payload["blocks"]

        section_blocks = [b for b in blocks if b.get("type") == "section"]
        all_text = " ".join(str(b) for b in section_blocks)

        assert "1" in all_text  # passed count
        assert "1" in all_text  # failed count

    @patch("posthog.temporal.ingestion_acceptance_test.slack.requests.post")
    def test_payload_contains_environment_info(
        self, mock_post: MagicMock, config: Config, passing_result: TestSuiteResult
    ) -> None:
        mock_post.return_value.raise_for_status = MagicMock()

        send_slack_notification(config, passing_result)

        payload = mock_post.call_args[1]["json"]
        blocks = payload["blocks"]

        context_blocks = [b for b in blocks if b.get("type") == "context"]
        all_text = " ".join(str(b) for b in context_blocks)

        assert "test.posthog.com" in all_text
        assert "12345" in all_text

    @patch("posthog.temporal.ingestion_acceptance_test.slack.requests.post")
    def test_failing_payload_contains_error_message(
        self, mock_post: MagicMock, config: Config, failing_result: TestSuiteResult
    ) -> None:
        mock_post.return_value.raise_for_status = MagicMock()

        send_slack_notification(config, failing_result)

        payload = mock_post.call_args[1]["json"]
        blocks = payload["blocks"]

        all_text = " ".join(str(b) for b in blocks)
        assert "test_failing" in all_text
        assert "AssertionError" in all_text

    @patch("posthog.temporal.ingestion_acceptance_test.slack.requests.post")
    def test_does_nothing_when_no_webhook_url(self, mock_post: MagicMock, passing_result: TestSuiteResult) -> None:
        config_no_webhook = Config(
            api_host="https://test.posthog.com",
            project_api_key="phc_test_key",
            project_id="12345",
            personal_api_key="phx_personal_key",
            slack_webhook_url=None,
        )

        send_slack_notification(config_no_webhook, passing_result)

        mock_post.assert_not_called()
