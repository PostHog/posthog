from concurrent.futures import ThreadPoolExecutor

import pytest
from unittest.mock import MagicMock, patch

from posthog.temporal.ingestion_acceptance_test.config import Config
from posthog.temporal.ingestion_acceptance_test.runner import AcceptanceTest, TestContext, run_tests
from posthog.temporal.ingestion_acceptance_test.test_cases_discovery import TestCase


@pytest.fixture
def config() -> Config:
    return Config(
        api_host="https://test.posthog.com",
        project_api_key="phc_test_key",
        project_id="12345",
        personal_api_key="phx_personal_key",
    )


@pytest.fixture
def mock_client() -> MagicMock:
    return MagicMock()


@pytest.fixture
def executor() -> ThreadPoolExecutor:
    return ThreadPoolExecutor(max_workers=4)


class TestRunTests:
    def test_instantiates_class_calls_setup_and_runs_method(
        self, config: Config, mock_client: MagicMock, executor: ThreadPoolExecutor
    ) -> None:
        call_order = []

        class FakeTest(AcceptanceTest):
            def __init__(self) -> None:
                call_order.append("init")

            def setup(self, ctx: TestContext) -> None:
                call_order.append("setup")

            def test_method(self) -> None:
                call_order.append("test_method")

        tests = [TestCase(module_name="test_mod", test_class=FakeTest, method_name="test_method")]

        run_tests(config, tests, mock_client, executor)

        assert call_order == ["init", "setup", "test_method"]

    def test_returns_passed_status_and_correct_names(
        self, config: Config, mock_client: MagicMock, executor: ThreadPoolExecutor
    ) -> None:
        class FakeTest(AcceptanceTest):
            def test_method(self) -> None:
                pass

        tests = [TestCase(module_name="test_mod", test_class=FakeTest, method_name="test_method")]

        result = run_tests(config, tests, mock_client, executor)

        assert result.passed_count == 1
        assert result.results[0].status == "passed"
        assert result.results[0].test_name == "test_method"
        assert result.results[0].test_file == "test_mod::FakeTest::test_method"

    def test_returns_failed_status_for_assertion_error(
        self, config: Config, mock_client: MagicMock, executor: ThreadPoolExecutor
    ) -> None:
        class FakeTest(AcceptanceTest):
            def test_method(self) -> None:
                raise AssertionError("expected failure")

        tests = [TestCase(module_name="test_mod", test_class=FakeTest, method_name="test_method")]

        result = run_tests(config, tests, mock_client, executor)

        assert result.failed_count == 1
        assert result.results[0].status == "failed"
        assert result.results[0].error_message is not None
        assert "expected failure" in result.results[0].error_message
        assert result.results[0].error_details is not None
        assert result.results[0].error_details["type"] == "AssertionError"

    def test_returns_error_status_for_unexpected_exception(
        self, config: Config, mock_client: MagicMock, executor: ThreadPoolExecutor
    ) -> None:
        class FakeTest(AcceptanceTest):
            def test_method(self) -> None:
                raise ValueError("something broke")

        tests = [TestCase(module_name="test_mod", test_class=FakeTest, method_name="test_method")]

        result = run_tests(config, tests, mock_client, executor)

        assert result.error_count == 1
        assert result.results[0].status == "error"
        assert result.results[0].error_message is not None
        assert "something broke" in result.results[0].error_message
        assert result.results[0].error_details is not None
        assert result.results[0].error_details["type"] == "ValueError"

    def test_runs_multiple_tests_and_aggregates_results(
        self, config: Config, mock_client: MagicMock, executor: ThreadPoolExecutor
    ) -> None:
        class PassingTest(AcceptanceTest):
            def test_pass(self) -> None:
                pass

        class FailingTest(AcceptanceTest):
            def test_fail(self) -> None:
                raise AssertionError()

        tests = [
            TestCase(module_name="test_mod", test_class=PassingTest, method_name="test_pass"),
            TestCase(module_name="test_mod", test_class=FailingTest, method_name="test_fail"),
        ]

        result = run_tests(config, tests, mock_client, executor)

        assert result.total_count == 2
        assert result.passed_count == 1
        assert result.failed_count == 1

    def test_calls_client_shutdown(self, config: Config, mock_client: MagicMock, executor: ThreadPoolExecutor) -> None:
        class FakeTest(AcceptanceTest):
            def test_method(self) -> None:
                pass

        tests = [TestCase(module_name="test_mod", test_class=FakeTest, method_name="test_method")]

        run_tests(config, tests, mock_client, executor)

        mock_client.shutdown.assert_called_once()

    def test_returns_environment_from_config(
        self, config: Config, mock_client: MagicMock, executor: ThreadPoolExecutor
    ) -> None:
        class FakeTest(AcceptanceTest):
            def test_method(self) -> None:
                pass

        tests = [TestCase(module_name="test_mod", test_class=FakeTest, method_name="test_method")]

        result = run_tests(config, tests, mock_client, executor)

        assert result.environment["api_host"] == "https://test.posthog.com"
        assert result.environment["project_id"] == "12345"

    @patch("posthog.temporal.ingestion_acceptance_test.runner.as_completed")
    def test_submits_all_tests_to_executor(
        self, mock_as_completed: MagicMock, config: Config, mock_client: MagicMock
    ) -> None:
        mock_executor = MagicMock()
        mock_futures = [MagicMock(), MagicMock(), MagicMock()]
        for f in mock_futures:
            f.result.return_value = MagicMock(status="passed")
        mock_executor.submit.side_effect = mock_futures
        mock_as_completed.return_value = mock_futures

        class FakeTest1(AcceptanceTest):
            def test_one(self) -> None:
                pass

        class FakeTest2(AcceptanceTest):
            def test_two(self) -> None:
                pass

        class FakeTest3(AcceptanceTest):
            def test_three(self) -> None:
                pass

        tests = [
            TestCase(module_name="test_mod", test_class=FakeTest1, method_name="test_one"),
            TestCase(module_name="test_mod", test_class=FakeTest2, method_name="test_two"),
            TestCase(module_name="test_mod", test_class=FakeTest3, method_name="test_three"),
        ]

        run_tests(config, tests, mock_client, mock_executor)

        assert mock_executor.submit.call_count == 3
