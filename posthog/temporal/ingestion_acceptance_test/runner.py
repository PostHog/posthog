"""Test runner for acceptance tests without pytest dependency."""

import time
import inspect
import importlib
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

from .client import PostHogClient
from .config import Config
from .results import TestResult, TestSuiteResult


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


@dataclass
class TestCase:
    """A discovered test case."""

    module_name: str
    test_class: type[AcceptanceTest]
    method_name: str

    @property
    def full_name(self) -> str:
        return f"{self.module_name}::{self.test_class.__name__}::{self.method_name}"


def discover_tests() -> list[TestCase]:
    """Discover all test cases in the tests package by scanning for test_*.py files."""
    tests_dir = Path(__file__).parent / "tests"
    base_package = "posthog.temporal.ingestion_acceptance_test.tests"

    tests: list[TestCase] = []

    for test_file in tests_dir.rglob("test_*.py"):
        relative_path = test_file.relative_to(tests_dir)
        module_parts = list(relative_path.with_suffix("").parts)
        module_name = f"{base_package}.{'.'.join(module_parts)}"

        module = importlib.import_module(module_name)

        for name, cls in inspect.getmembers(module, inspect.isclass):
            if not name.startswith("Test"):
                continue
            if not issubclass(cls, AcceptanceTest):
                continue

            for method_name in dir(cls):
                if not method_name.startswith("test_"):
                    continue

                tests.append(
                    TestCase(
                        module_name=test_file.stem,
                        test_class=cls,
                        method_name=method_name,
                    )
                )

    return tests


def run_single_test(
    test_case: TestCase,
    ctx: TestContext,
) -> TestResult:
    """Run a single test and return its result."""
    start_time = time.time()
    status = "passed"
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


def run_tests(config: Config) -> TestSuiteResult:
    """Run all acceptance tests and return structured results.

    Args:
        config: Configuration for the test run.

    Returns:
        TestSuiteResult with all test outcomes.
    """
    start_time = time.time()
    client = PostHogClient(config)
    results: list[TestResult] = []

    try:
        tests = discover_tests()
        ctx = TestContext(client=client, config=config)

        with ThreadPoolExecutor() as executor:
            futures = {executor.submit(run_single_test, test_case, ctx): test_case for test_case in tests}
            for future in as_completed(futures):
                results.append(future.result())

    finally:
        client.shutdown()

    return TestSuiteResult(
        results=results,
        total_duration_seconds=time.time() - start_time,
        environment=config.to_safe_dict(),
    )
