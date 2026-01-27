"""Root conftest.py - pytest hooks for result collection and reporting."""

import json
import time
import traceback
from pathlib import Path

import pytest

from .config import Config
from .results import TestResult, TestSuiteResult

# Global state for collecting results
_test_results: list[TestResult] = []
_suite_start_time: float = 0
_config: Config | None = None


def pytest_addoption(parser: pytest.Parser) -> None:
    """Add custom command line options."""
    parser.addoption(
        "--results-output",
        action="store",
        default=None,
        help="Path to write JSON results file for alerting integration",
    )


def pytest_configure(config: pytest.Config) -> None:
    """Initialize test suite state."""
    global _suite_start_time, _config, _test_results
    _suite_start_time = time.time()
    _test_results = []

    try:
        _config = Config.from_env()
    except ValueError:
        _config = None


def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo) -> None:
    """Capture each test result after execution."""
    if call.when != "call":
        return

    error_message = None
    error_details = None
    status = "passed"

    if call.excinfo is not None:
        if call.excinfo.errisinstance(pytest.skip.Exception):
            status = "skipped"
            error_message = str(call.excinfo.value)
        else:
            status = "failed" if call.excinfo.errisinstance(AssertionError) else "error"
            error_message = str(call.excinfo.value)
            error_details = {
                "type": call.excinfo.type.__name__,
                "traceback": "".join(traceback.format_exception(call.excinfo.value)),
            }

    result = TestResult(
        test_name=item.name,
        test_file=str(Path(item.fspath).relative_to(Path.cwd())) if item.fspath else "",
        status=status,
        duration_seconds=call.duration,
        error_message=error_message,
        error_details=error_details,
    )
    _test_results.append(result)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Prepare results after all tests complete."""
    global _suite_result, _test_results, _suite_start_time, _config

    total_duration = time.time() - _suite_start_time
    environment = _config.to_safe_dict() if _config else {"error": "Config not loaded"}

    _suite_result = TestSuiteResult(
        results=_test_results,
        total_duration_seconds=total_duration,
        environment=environment,
    )

    # Write JSON output if requested
    output_path = session.config.getoption("--results-output")
    if output_path:
        with open(output_path, "w") as f:
            json.dump(_suite_result.to_dict(), f, indent=2)


# Store suite result for terminal summary
_suite_result: TestSuiteResult | None = None


def pytest_terminal_summary(terminalreporter: pytest.TerminalReporter) -> None:
    """Print detailed report AFTER pytest's default summary."""
    global _suite_result

    if _suite_result is None:
        return

    terminalreporter.write_line("")
    terminalreporter.write_line("=" * 70)
    for line in _suite_result.format_report().split("\n"):
        terminalreporter.write_line(line)
    terminalreporter.write_line("=" * 70)
