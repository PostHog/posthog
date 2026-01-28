"""Test runner for acceptance tests without pytest dependency."""

import time
import inspect
import traceback
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any

from .client import PostHogClient
from .config import Config
from .results import TestResult, TestSuiteResult
from .slack import send_slack_notification


@dataclass
class TestCase:
    """A discovered test case."""

    name: str
    module_name: str
    test_class: type
    method_name: str

    @property
    def full_name(self) -> str:
        return f"{self.module_name}::{self.test_class.__name__}::{self.method_name}"


def discover_tests() -> list[TestCase]:
    """Discover all test cases in the tests package."""
    from .tests.capture import test_basic_capture, test_event_properties_capture

    test_modules = [
        test_basic_capture,
        test_event_properties_capture,
    ]

    tests: list[TestCase] = []

    for module in test_modules:
        module_name = module.__name__.split(".")[-1]

        for name, cls in inspect.getmembers(module, inspect.isclass):
            if not name.startswith("Test"):
                continue

            for method_name, _method in inspect.getmembers(cls, inspect.isfunction):
                if not method_name.startswith("test_"):
                    continue

                tests.append(
                    TestCase(
                        name=method_name,
                        module_name=module_name,
                        test_class=cls,
                        method_name=method_name,
                    )
                )

    return tests


def run_single_test(
    test_case: TestCase,
    client: PostHogClient,
    config: Config,
) -> TestResult:
    """Run a single test and return its result."""
    start_time = time.time()
    status = "passed"
    error_message = None
    error_details = None

    try:
        instance = test_case.test_class()
        method = getattr(instance, test_case.method_name)

        sig = inspect.signature(method)
        kwargs: dict[str, Any] = {}
        if "client" in sig.parameters:
            kwargs["client"] = client
        if "config" in sig.parameters:
            kwargs["config"] = config

        method(**kwargs)

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
        test_name=test_case.name,
        test_file=test_case.full_name,
        status=status,
        duration_seconds=duration,
        error_message=error_message,
        error_details=error_details,
    )


def run_tests(
    config: Config | None = None,
    test_filter: Callable[[TestCase], bool] | None = None,
) -> TestSuiteResult:
    """Run all acceptance tests and return structured results.

    Args:
        config: Optional configuration. If not provided, loads from environment.
        test_filter: Optional filter function to select which tests to run.

    Returns:
        TestSuiteResult with all test outcomes.
    """
    start_time = time.time()

    if config is None:
        config = Config()

    client = PostHogClient(config)
    results: list[TestResult] = []

    try:
        tests = discover_tests()

        if test_filter:
            tests = [t for t in tests if test_filter(t)]

        with ThreadPoolExecutor() as executor:
            futures = {executor.submit(run_single_test, test_case, client, config): test_case for test_case in tests}
            for future in as_completed(futures):
                results.append(future.result())

    finally:
        client.shutdown()

    suite_result = TestSuiteResult(
        results=results,
        total_duration_seconds=time.time() - start_time,
        environment=config.to_safe_dict(),
    )

    send_slack_notification(config, suite_result)

    return suite_result
