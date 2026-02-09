"""Test result types and reporters for alerting integration."""

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal


@dataclass
class TestResult:
    """Result of a single test execution."""

    test_name: str
    test_file: str
    status: Literal["passed", "failed", "error"]
    duration_seconds: float
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    error_message: str | None = None
    error_details: dict[str, Any] | None = None


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
    def total_count(self) -> int:
        return len(self.results)

    @property
    def success(self) -> bool:
        return self.failed_count == 0 and self.error_count == 0

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
