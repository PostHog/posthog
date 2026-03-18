"""Terminal report formatting for test results."""

from .results import TestSuiteResult


def format_terminal_report(result: TestSuiteResult) -> str:
    """Format a detailed report suitable for console output."""
    sections = [
        _format_header(result),
        _format_environment(result),
        _format_summary(result),
        _format_failed_tests(result),
        _format_passed_tests(result),
    ]
    return "\n".join(s for s in sections if s)


def _format_header(result: TestSuiteResult) -> str:
    status_emoji = "✅" if result.success else "❌"
    status_text = "PASSED" if result.success else "FAILED"
    return f"{status_emoji} Ingestion Acceptance Tests: {status_text}\n"


def _format_environment(result: TestSuiteResult) -> str:
    return (
        f"Environment: {result.environment.get('api_host', 'unknown')}\n"
        f"Project ID:  {result.environment.get('project_id', 'unknown')}\n"
        f"Timestamp:   {result.timestamp}\n"
    )


def _format_summary(result: TestSuiteResult) -> str:
    return (
        f"Summary:\n"
        f"  Total:    {result.total_count}\n"
        f"  Passed:   {result.passed_count}\n"
        f"  Failed:   {result.failed_count}\n"
        f"  Errors:   {result.error_count}\n"
        f"  Duration: {result.total_duration_seconds:.2f}s"
    )


def _format_failed_tests(result: TestSuiteResult) -> str:
    failed_tests = [r for r in result.results if r.status in ("failed", "error")]
    if not failed_tests:
        return ""

    lines = ["\nFailed Tests:"]
    for test_result in failed_tests:
        status_indicator = "❌" if test_result.status == "failed" else "💥"
        lines.append(f"\n  {status_indicator} {test_result.test_file}::{test_result.test_name}")
        lines.append(f"     Status: {test_result.status}")
        lines.append(f"     Duration: {test_result.duration_seconds:.2f}s")
        if test_result.error_message:
            error_msg = (
                test_result.error_message[:500] + "..."
                if len(test_result.error_message) > 500
                else test_result.error_message
            )
            lines.append(f"     Error: {error_msg}")
        if test_result.error_details and test_result.error_details.get("traceback"):
            tb_lines = test_result.error_details["traceback"].strip().split("\n")
            relevant_tb = tb_lines[-6:] if len(tb_lines) > 6 else tb_lines
            lines.append("     Traceback (last lines):")
            lines.extend(f"       {tb_line}" for tb_line in relevant_tb)
    return "\n".join(lines)


def _format_passed_tests(result: TestSuiteResult) -> str:
    passed_tests = [r for r in result.results if r.status == "passed"]
    if not passed_tests:
        return ""

    lines = ["\nPassed Tests:"]
    lines.extend(f"  ✅ {r.test_file}::{r.test_name} ({r.duration_seconds:.2f}s)" for r in passed_tests)
    return "\n".join(lines)
