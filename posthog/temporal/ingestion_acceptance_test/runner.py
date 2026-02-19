"""Test runner for acceptance tests without pytest dependency."""

import time
import traceback
from concurrent.futures import Executor, as_completed
from dataclasses import dataclass
from typing import Literal

from .client import CapturedEvent, PostHogClient
from .config import Config
from .results import TestResult, TestSuiteResult
from .test_cases_discovery import TestCase


@dataclass
class TestContext:
    """Context provided to all acceptance tests."""

    client: PostHogClient
    config: Config


class AcceptanceTest:
    """Base class for acceptance tests."""

    client: PostHogClient
    config: Config

    def setup(self, ctx: TestContext) -> None:
        """Called before each test method."""
        self.client = ctx.client
        self.config = ctx.config

    def assert_properties_contain(self, actual: dict, expected: dict, context: str = "") -> None:
        """Assert that actual dict contains all expected key-value pairs."""
        prefix = f"{context}: " if context else ""
        for key, expected_value in expected.items():
            actual_value = actual.get(key)
            assert actual_value == expected_value, f"{prefix}Expected {key}={expected_value!r}, got {actual_value!r}"

    def assert_event(
        self, event: CapturedEvent | None, expected_uuid: str, expected_name: str, expected_distinct_id: str
    ) -> CapturedEvent:
        """Assert event was found and has expected uuid, name, and distinct_id. Returns the event."""
        assert event is not None, f"Event {expected_uuid} not found within {self.config.event_timeout_seconds}s timeout"
        assert event.uuid == expected_uuid, f"Expected uuid={expected_uuid}, got {event.uuid}"
        assert event.event == expected_name, f"Expected event={expected_name}, got {event.event}"
        assert event.distinct_id == expected_distinct_id, (
            f"Expected distinct_id={expected_distinct_id}, got {event.distinct_id}"
        )
        return event


def _run_single_test(
    test_case: TestCase,
    ctx: TestContext,
) -> TestResult:
    """Run a single test and return its result."""
    start_time = time.time()
    status: Literal["passed", "failed", "error"] = "passed"
    error_message = None
    error_details = None

    try:
        instance = test_case.test_class()
        instance.setup(ctx)
        method = getattr(instance, test_case.method_name)
        method()

    except AssertionError as e:
        status = "failed"
        error_message = str(e)
        error_details = {
            "type": "AssertionError",
            "traceback": traceback.format_exc(),
        }
    except Exception as e:
        status = "error"
        error_message = str(e)
        error_details = {
            "type": type(e).__name__,
            "traceback": traceback.format_exc(),
        }

    duration = time.time() - start_time

    return TestResult(
        test_name=test_case.method_name,
        test_file=test_case.full_name,
        status=status,
        duration_seconds=duration,
        error_message=error_message,
        error_details=error_details,
    )


def run_tests(
    config: Config,
    tests: list[TestCase],
    client: PostHogClient,
    executor: Executor,
) -> TestSuiteResult:
    """Run all acceptance tests and return structured results.

    Args:
        config: Configuration for the test run.
        tests: List of test cases to run.
        client: PostHog client for API interactions.
        executor: Executor for running tests in parallel.

    Returns:
        TestSuiteResult with all test outcomes.
    """
    start_time = time.time()
    results: list[TestResult] = []

    try:
        ctx = TestContext(client=client, config=config)

        futures = {executor.submit(_run_single_test, test_case, ctx): test_case for test_case in tests}
        for future in as_completed(futures):
            results.append(future.result())

    finally:
        client.shutdown()

    return TestSuiteResult(
        results=results,
        total_duration_seconds=time.time() - start_time,
        environment=config.to_safe_dict(),
    )
