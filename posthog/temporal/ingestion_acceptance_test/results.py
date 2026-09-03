"""Test result types and reporters for alerting integration."""

from dataclasses import asdict, field
from datetime import UTC, datetime
from typing import Any, Literal

from posthog.dataclasses import frozen

FailureClass = Literal["connection_error", "event_missing", "person_missing", "assertion", "error"]

# Exception types raised when the test cannot reach ClickHouse or the API at
# all. These are infrastructure or harness problems, not ingestion problems.
CONNECTION_ERROR_TYPES = frozenset(
    {
        "SocketTimeoutError",
        "NetworkError",
        "ConnectionError",
        "ConnectionResetError",
        "ConnectionRefusedError",
        "EOFError",
        "OSError",
        "TimeoutError",
        "ReadTimeout",
        "ConnectTimeout",
    }
)


@frozen
class CapturedEventRef:
    """An event the test sent through the SDK, kept so a failure can name it."""

    uuid: str
    event: str
    distinct_id: str


@frozen
class TestResult:
    """Result of a single test execution."""

    test_name: str
    test_file: str
    status: Literal["passed", "failed", "error"]
    duration_seconds: float
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    error_message: str | None = None
    error_details: dict[str, Any] | None = None
    captured_events: list[CapturedEventRef] = field(default_factory=list)

    @property
    def error_type(self) -> str | None:
        if not self.error_details:
            return None
        error_type = self.error_details.get("type")
        return str(error_type) if error_type else None


def classify_failure(result: TestResult) -> FailureClass | None:
    """Sort a failed test into the bucket an investigator should start from.

    Returns None for passing tests.
    """
    if result.status == "passed":
        return None
    error_type = result.error_type or ""
    if error_type in CONNECTION_ERROR_TYPES or "Timeout" in error_type or "Connection" in error_type:
        return "connection_error"
    if error_type != "AssertionError":
        return "error"
    message = result.error_message or ""
    if "not found within" not in message:
        return "assertion"
    return "person_missing" if message.startswith("Person") else "event_missing"


@frozen
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
    def total_count(self) -> int:
        return len(self.results)

    @property
    def success(self) -> bool:
        return self.failed_count == 0 and self.error_count == 0

    @property
    def failed_results(self) -> list[TestResult]:
        return [r for r in self.results if r.status != "passed"]

    def to_dict(self) -> dict[str, Any]:
        return {
            "results": [asdict(r) for r in self.results],
            "total_duration_seconds": self.total_duration_seconds,
            "environment": self.environment,
            "timestamp": self.timestamp,
            "summary": {
                "total": self.total_count,
                "passed": self.passed_count,
                "failed": self.failed_count,
                "errors": self.error_count,
                "success": self.success,
            },
        }
