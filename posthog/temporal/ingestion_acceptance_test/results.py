"""Test result types and reporters for alerting integration."""

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal


@dataclass
class TestResult:
    """Result of a single test execution."""

    test_name: str
    test_file: str
    status: Literal["passed", "failed", "error", "skipped"]
    duration_seconds: float
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    error_message: str | None = None
    error_details: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TestSuiteResult:
    """Result of a full test suite execution."""

    results: list[TestResult]
    total_duration_seconds: float
    environment: dict[str, str]
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    @property
    def passed_count(self) -> int:
        return sum(1 for r in self.results if r.status == "passed")

    @property
    def failed_count(self) -> int:
        return sum(1 for r in self.results if r.status == "failed")

    @property
    def error_count(self) -> int:
        return sum(1 for r in self.results if r.status == "error")

    @property
    def skipped_count(self) -> int:
        return sum(1 for r in self.results if r.status == "skipped")

    @property
    def total_count(self) -> int:
        return len(self.results)

    @property
    def success(self) -> bool:
        return self.failed_count == 0 and self.error_count == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "results": [r.to_dict() for r in self.results],
            "total_duration_seconds": self.total_duration_seconds,
            "environment": self.environment,
            "timestamp": self.timestamp,
            "summary": {
                "total": self.total_count,
                "passed": self.passed_count,
                "failed": self.failed_count,
                "errors": self.error_count,
                "skipped": self.skipped_count,
                "success": self.success,
            },
        }

    def format_report(self) -> str:
        """Format a detailed report suitable for console output or Slack."""
        lines: list[str] = []

        # Header with status
        status_emoji = "✅" if self.success else "❌"
        status_text = "PASSED" if self.success else "FAILED"
        lines.append(f"{status_emoji} Ingestion Acceptance Tests: {status_text}")
        lines.append("")

        # Environment
        lines.append(f"Environment: {self.environment.get('api_host', 'unknown')}")
        lines.append(f"Project ID:  {self.environment.get('project_id', 'unknown')}")
        lines.append(f"Timestamp:   {self.timestamp}")
        lines.append("")

        # Summary
        lines.append("Summary:")
        lines.append(f"  Total:    {self.total_count}")
        lines.append(f"  Passed:   {self.passed_count}")
        lines.append(f"  Failed:   {self.failed_count}")
        lines.append(f"  Errors:   {self.error_count}")
        lines.append(f"  Skipped:  {self.skipped_count}")
        lines.append(f"  Duration: {self.total_duration_seconds:.2f}s")

        # Failed tests details
        failed_tests = [r for r in self.results if r.status in ("failed", "error")]
        if failed_tests:
            lines.append("")
            lines.append("Failed Tests:")
            for result in failed_tests:
                lines.append("")
                status_indicator = "❌" if result.status == "failed" else "💥"
                lines.append(f"  {status_indicator} {result.test_file}::{result.test_name}")
                lines.append(f"     Status: {result.status}")
                lines.append(f"     Duration: {result.duration_seconds:.2f}s")
                if result.error_message:
                    # Truncate long error messages for readability
                    error_msg = result.error_message
                    if len(error_msg) > 500:
                        error_msg = error_msg[:500] + "..."
                    lines.append(f"     Error: {error_msg}")
                if result.error_details and result.error_details.get("traceback"):
                    # Include last few lines of traceback
                    tb_lines = result.error_details["traceback"].strip().split("\n")
                    # Get last 6 lines of traceback for context
                    relevant_tb = tb_lines[-6:] if len(tb_lines) > 6 else tb_lines
                    lines.append("     Traceback (last lines):")
                    for tb_line in relevant_tb:
                        lines.append(f"       {tb_line}")

        # Passed tests (brief)
        passed_tests = [r for r in self.results if r.status == "passed"]
        if passed_tests:
            lines.append("")
            lines.append("Passed Tests:")
            for result in passed_tests:
                lines.append(f"  ✅ {result.test_file}::{result.test_name} ({result.duration_seconds:.2f}s)")

        return "\n".join(lines)
