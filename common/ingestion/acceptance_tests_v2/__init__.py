"""PostHog Ingestion Acceptance Tests.

This package contains acceptance tests that run against PostHog APIs
to verify end-to-end ingestion functionality.

Usage:
    # Run from command line
    python -m common.ingestion.acceptance_tests_v2

    # Run programmatically
    from common.ingestion.acceptance_tests_v2 import run_tests
    result = run_tests()
    print(result.format_report())

    # Run from Temporal activity
    from common.ingestion.acceptance_tests_v2 import run_tests, Config
    config = Config(api_host="...", ...)
    result = run_tests(config=config)
    return result.to_dict()
"""

from .config import Config
from .results import TestResult, TestSuiteResult
from .runner import run_tests

__all__ = [
    "Config",
    "TestResult",
    "TestSuiteResult",
    "run_tests",
]
