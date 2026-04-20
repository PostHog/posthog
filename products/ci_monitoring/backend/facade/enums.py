"""Exported enums and constants for ci_monitoring."""

from enum import StrEnum


class TestExecutionStatus(StrEnum):
    """Outcome of a single test execution."""

    PASSED = "passed"
    FAILED = "failed"
    FLAKY = "flaky"  # Failed then passed on rerun
    SKIPPED = "skipped"
    ERROR = "error"  # Infrastructure error, not a test failure


class CIRunConclusion(StrEnum):
    """Conclusion of a CI workflow run."""

    SUCCESS = "success"
    FAILURE = "failure"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


class QuarantineState(StrEnum):
    """State of a test quarantine."""

    ACTIVE = "active"
    RESOLVED = "resolved"


class TestSuite(StrEnum):
    """Known test suite categories."""

    BACKEND = "backend"
    E2E = "e2e"
    STORYBOOK = "storybook"
    NODEJS = "nodejs"
    RUST = "rust"
    OTHER = "other"
