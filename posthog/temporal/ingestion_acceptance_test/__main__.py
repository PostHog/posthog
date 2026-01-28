"""Command-line entry point for running acceptance tests."""

import sys
import logging

from posthog.temporal.ingestion_acceptance_test.runner import run_tests

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logger = logging.getLogger(__name__)
    result = run_tests()
    logger.info(result.format_report())
    sys.exit(0 if result.success else 1)
