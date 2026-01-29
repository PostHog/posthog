"""Command-line entry point for running acceptance tests."""

import sys
import logging

from posthog.temporal.ingestion_acceptance_test.config import Config
from posthog.temporal.ingestion_acceptance_test.runner import run_tests
from posthog.temporal.ingestion_acceptance_test.terminal_report import format_terminal_report

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logger = logging.getLogger(__name__)
    config = Config()
    result = run_tests(config)
    logger.info(format_terminal_report(result))
    sys.exit(0 if result.success else 1)
