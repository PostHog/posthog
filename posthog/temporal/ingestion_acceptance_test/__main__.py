"""Command-line entry point for running acceptance tests."""

import sys
import logging
from concurrent.futures import ThreadPoolExecutor

import posthoganalytics

from posthog.temporal.ingestion_acceptance_test.client import PostHogClient
from posthog.temporal.ingestion_acceptance_test.config import Config
from posthog.temporal.ingestion_acceptance_test.runner import run_tests
from posthog.temporal.ingestion_acceptance_test.terminal_report import format_terminal_report
from posthog.temporal.ingestion_acceptance_test.test_cases_discovery import discover_tests

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logger = logging.getLogger(__name__)
    config = Config()

    posthog_sdk = posthoganalytics.Posthog(
        config.project_api_key,
        host=config.api_host,
        debug=True,
        sync_mode=True,
    )

    tests = discover_tests()
    client = PostHogClient(config, posthog_sdk)
    with ThreadPoolExecutor() as executor:
        result = run_tests(config, tests, client, executor)
    logger.info(format_terminal_report(result))
    sys.exit(0 if result.success else 1)
