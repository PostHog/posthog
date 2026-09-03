from urllib.parse import unquote

import pytest
from unittest.mock import MagicMock, patch

from posthog.temporal.ingestion_acceptance_test.config import Config
from posthog.temporal.ingestion_acceptance_test.results import CapturedEventRef, TestResult, TestSuiteResult
from posthog.temporal.ingestion_acceptance_test.runner import RunningTestSnapshot
from posthog.temporal.ingestion_acceptance_test.slack import (
    RunContext,
    send_slack_notification,
    send_slack_timeout_notification,
)


@pytest.fixture
def config() -> Config:
    return Config(
        api_host="https://test.posthog.com",
        project_api_key="phc_test_key",
        team_id=12345,
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
        environment={"api_host": "https://test.posthog.com", "team_id": "12345"},
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
        environment={"api_host": "https://test.posthog.com", "team_id": "12345"},
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
        assert "main lane" in header_text

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

        all_text = " ".join(str(b) for b in blocks)

        assert "test_file.py" in all_text
        assert "AssertionError" in all_text

    @pytest.mark.parametrize(
        "error_type, error_message, expected_class, expected_severity",
        [
            ("SocketTimeoutError", "Code: 209. (ch-offline:9440)", "connection_error", "warning"),
            ("AssertionError", "Event abc-123 not found within 3600s timeout", "event_missing", "critical"),
            ("AssertionError", "Person A not found within time budget", "person_missing", "critical"),
            ("AssertionError", "Expected name='a', got 'b'", "assertion", "critical"),
        ],
        ids=["connection_error", "event_missing", "person_missing", "assertion"],
    )
    @patch("posthog.temporal.ingestion_acceptance_test.slack.requests.post")
    def test_payload_carries_failure_class_and_alert_metadata(
        self,
        mock_post: MagicMock,
        config: Config,
        error_type: str,
        error_message: str,
        expected_class: str,
        expected_severity: str,
    ) -> None:
        mock_post.return_value.raise_for_status = MagicMock()
        result = TestSuiteResult(
            results=[
                TestResult(
                    test_name="test_x",
                    test_file="acceptance_test_x::TestX::test_x",
                    status="failed" if error_type == "AssertionError" else "error",
                    duration_seconds=1.0,
                    error_message=error_message,
                    error_details={"type": error_type, "traceback": "..."},
                    captured_events=[CapturedEventRef(uuid="abc-123", event="$test", distinct_id="did-1")],
                )
            ],
            total_duration_seconds=1.0,
            environment={},
            timestamp="2024-01-01T00:00:00Z",
        )

        send_slack_notification(config, result)

        blocks = mock_post.call_args[1]["json"]["blocks"]
        sections = [b["text"]["text"] for b in blocks if b.get("type") == "section"]
        failed_block = next(t for t in sections if "acceptance_test_x::TestX::test_x" in t)
        assert f"Failure class: `{expected_class}`" in failed_block
        assert f"{error_type}: {error_message}" in failed_block
        assert "uuid `abc-123` distinct_id `did-1`" in failed_block

        metadata_block = next(t for t in sections if t.startswith("Environment:"))
        assert "Environment: dev" in metadata_block
        assert f"Severity: {expected_severity}" in metadata_block
        assert f"Failure class: {expected_class}" in metadata_block

    @patch("posthog.temporal.ingestion_acceptance_test.slack.requests.post")
    def test_payload_stays_within_slack_block_kit_limits(self, mock_post: MagicMock, config: Config) -> None:
        mock_post.return_value.raise_for_status = MagicMock()
        results = [
            TestResult(
                test_name=f"t{i}",
                test_file=f"acceptance_test_x::TestX::t{i}",
                status="failed",
                duration_seconds=1.0,
                error_message="x" * 5000,
                error_details={"type": "AssertionError"},
                captured_events=[CapturedEventRef(uuid=f"u-{i}-{j}", event="$e", distinct_id="d") for j in range(40)],
            )
            for i in range(80)
        ]
        result = TestSuiteResult(
            results=results, total_duration_seconds=1.0, environment={}, timestamp="2024-01-01T00:00:00Z"
        )

        send_slack_notification(config, result)

        blocks = mock_post.call_args[1]["json"]["blocks"]
        assert len(blocks) <= 50
        assert all(len(b["text"]["text"]) <= 3000 for b in blocks if b["type"] == "section")
        assert all(len(b["elements"][0]["text"]) <= 2000 for b in blocks if b["type"] == "context")
        assert "Unsuccessful run" in blocks[0]["text"]["text"]
        assert "Env: https://test.posthog.com" in blocks[-1]["elements"][0]["text"]
        assert "more block(s) not shown" in blocks[-2]["text"]["text"]

    @patch("posthog.temporal.ingestion_acceptance_test.slack.requests.post")
    def test_suite_failure_class_is_the_most_serious_one(self, mock_post: MagicMock, config: Config) -> None:
        mock_post.return_value.raise_for_status = MagicMock()
        result = TestSuiteResult(
            results=[
                TestResult(
                    test_name="a",
                    test_file="a",
                    status="error",
                    duration_seconds=1.0,
                    error_message="Code: 209.",
                    error_details={"type": "SocketTimeoutError"},
                ),
                TestResult(
                    test_name="b",
                    test_file="b",
                    status="failed",
                    duration_seconds=1.0,
                    error_message="Event x not found within 3600s timeout",
                    error_details={"type": "AssertionError"},
                ),
            ],
            total_duration_seconds=1.0,
            environment={},
            timestamp="2024-01-01T00:00:00Z",
        )

        send_slack_notification(config, result)

        blocks = mock_post.call_args[1]["json"]["blocks"]
        metadata_block = next(
            b["text"]["text"] for b in blocks if b["type"] == "section" and "Severity:" in b["text"]["text"]
        )
        assert "Failure class: event_missing" in metadata_block
        assert "Severity: critical" in metadata_block

    @patch("posthog.temporal.ingestion_acceptance_test.slack.requests.post")
    def test_links_to_temporal_run_loki_and_runbook(
        self, mock_post: MagicMock, failing_result: TestSuiteResult
    ) -> None:
        mock_post.return_value.raise_for_status = MagicMock()
        config = Config(
            api_host="https://us.posthog.com",
            project_api_key="phc_test_key",
            team_id=12345,
            slack_webhook_url="https://hooks.slack.com/services/T00/B00/XXX",
        )
        run_context = RunContext(
            workflow_id="wf-1",
            workflow_run_id="run-1",
            namespace="ns.abc",
            temporal_ui_host="https://cloud.temporal.io",
        )

        send_slack_notification(config, failing_result, run_context=run_context)

        blocks = mock_post.call_args[1]["json"]["blocks"]
        links_text = blocks[-1]["elements"][0]["text"]
        assert "<https://cloud.temporal.io/namespaces/ns.abc/workflows/wf-1/run-1/history|Temporal run>" in links_text
        assert "https://grafana.prod-us.posthog.dev/explore?left=" in links_text
        assert "temporal-worker-general-purpose" in unquote(links_text)
        assert (
            "<https://runbooks.posthog.com/services/ingestion/runbooks/ingestion-acceptance-test|Runbook>" in links_text
        )
        assert "Environment: prod-us" in " ".join(str(b) for b in blocks)

    @patch("posthog.temporal.ingestion_acceptance_test.slack.requests.post")
    def test_does_nothing_when_no_webhook_url(self, mock_post: MagicMock, failing_result: TestSuiteResult) -> None:
        config_no_webhook = Config(
            api_host="https://test.posthog.com",
            project_api_key="phc_test_key",
            team_id=12345,
            slack_webhook_url=None,
        )

        send_slack_notification(config_no_webhook, failing_result)

        mock_post.assert_not_called()


class TestSendSlackTimeoutNotification:
    @patch("posthog.temporal.ingestion_acceptance_test.slack.requests.post")
    def test_posts_timeout_message_to_webhook(self, mock_post: MagicMock, config: Config) -> None:
        mock_post.return_value.raise_for_status = MagicMock()

        result = send_slack_timeout_notification(config)

        assert result is True
        mock_post.assert_called_once()
        url = mock_post.call_args[0][0]
        assert url == "https://hooks.slack.com/services/T00/B00/XXX"

    @patch("posthog.temporal.ingestion_acceptance_test.slack.requests.post")
    def test_payload_contains_timeout_header(self, mock_post: MagicMock, config: Config) -> None:
        mock_post.return_value.raise_for_status = MagicMock()

        send_slack_timeout_notification(config)

        payload = mock_post.call_args[1]["json"]
        header_text = payload["blocks"][0]["text"]["text"]
        assert "Timed Out" in header_text
        assert "main lane" in header_text

    @patch("posthog.temporal.ingestion_acceptance_test.slack.requests.post")
    def test_payload_contains_environment_timeout_and_token_info(self, mock_post: MagicMock, config: Config) -> None:
        mock_post.return_value.raise_for_status = MagicMock()

        send_slack_timeout_notification(config)

        payload = mock_post.call_args[1]["json"]
        context_text = payload["blocks"][1]["elements"][0]["text"]
        assert "test.posthog.com" in context_text
        assert "12345" in context_text
        assert "3600s" in context_text
        assert "phc_test_k..." in context_text
        all_text = " ".join(str(b) for b in payload["blocks"])
        assert "Environment: dev" in all_text
        assert "Failure class: error" in all_text
        assert "Severity: warning" in all_text

    @pytest.mark.parametrize(
        "pending_polls, expected_class, expected_severity",
        [
            (["event UUID 'abc'"], "event_missing", "critical"),
            (["person with distinct_id 'abc'"], "person_missing", "critical"),
            (["events for person 'p1'", "person with distinct_id 'abc'"], "event_missing", "critical"),
            ([None], "error", "warning"),
        ],
        ids=["event_poll", "person_poll", "mixed_polls", "no_poll"],
    )
    @patch("posthog.temporal.ingestion_acceptance_test.slack.requests.post")
    def test_timeout_is_classified_by_what_was_pending(
        self,
        mock_post: MagicMock,
        config: Config,
        pending_polls: list[str | None],
        expected_class: str,
        expected_severity: str,
    ) -> None:
        mock_post.return_value.raise_for_status = MagicMock()
        running = [RunningTestSnapshot(name=f"t{i}", pending_poll=p) for i, p in enumerate(pending_polls)]

        send_slack_timeout_notification(config, running_tests=running)

        all_text = " ".join(str(b) for b in mock_post.call_args[1]["json"]["blocks"])
        assert f"Failure class: {expected_class}" in all_text
        assert f"Severity: {expected_severity}" in all_text

    @patch("posthog.temporal.ingestion_acceptance_test.slack.requests.post")
    def test_does_nothing_when_no_webhook_url(self, mock_post: MagicMock) -> None:
        config_no_webhook = Config(
            api_host="https://test.posthog.com",
            project_api_key="phc_test_key",
            team_id=12345,
            slack_webhook_url=None,
        )

        result = send_slack_timeout_notification(config_no_webhook)

        assert result is True
        mock_post.assert_not_called()

    @pytest.mark.parametrize(
        "running_tests, expected_in_text, not_expected_in_text",
        [
            (
                [
                    RunningTestSnapshot(name="TestAlias::test_alias", pending_poll="person with distinct_id 'abc-123'"),
                    RunningTestSnapshot(name="TestMerge::test_merge", pending_poll="events for person 'person-789'"),
                ],
                [
                    "TestAlias::test_alias",
                    "person with distinct_id 'abc-123'",
                    "TestMerge::test_merge",
                    "Still running (2)",
                ],
                [],
            ),
            (
                [RunningTestSnapshot(name="TestBasic::test_capture", pending_poll=None)],
                ["TestBasic::test_capture"],
                ["waiting for"],
            ),
        ],
        ids=["with_poll_descriptions", "without_poll_description"],
    )
    @patch("posthog.temporal.ingestion_acceptance_test.slack.requests.post")
    def test_payload_renders_running_tests(
        self,
        mock_post: MagicMock,
        config: Config,
        running_tests: list[RunningTestSnapshot],
        expected_in_text: list[str],
        not_expected_in_text: list[str],
    ) -> None:
        mock_post.return_value.raise_for_status = MagicMock()

        send_slack_timeout_notification(config, running_tests=running_tests)

        payload = mock_post.call_args[1]["json"]
        running_text = payload["blocks"][2]["text"]["text"]
        for expected in expected_in_text:
            assert expected in running_text
        for not_expected in not_expected_in_text:
            assert not_expected not in running_text
