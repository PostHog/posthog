"""Activities for ingestion acceptance test workflow."""

import asyncio
from concurrent.futures import ThreadPoolExecutor

import structlog
import posthoganalytics
import temporalio.activity

from posthog.temporal.ingestion_acceptance_test.client import PostHogClient
from posthog.temporal.ingestion_acceptance_test.config import Config
from posthog.temporal.ingestion_acceptance_test.results import TestSuiteResult
from posthog.temporal.ingestion_acceptance_test.runner import run_tests
from posthog.temporal.ingestion_acceptance_test.slack import send_slack_notification
from posthog.temporal.ingestion_acceptance_test.test_cases_discovery import discover_tests

logger = structlog.get_logger(__name__)


@temporalio.activity.defn
async def run_ingestion_acceptance_tests() -> dict:
    """Run ingestion acceptance tests and return results.

    Configuration is loaded from environment variables:
    - INGESTION_ACCEPTANCE_TEST_API_HOST
    - INGESTION_ACCEPTANCE_TEST_PROJECT_API_KEY
    - INGESTION_ACCEPTANCE_TEST_PROJECT_ID
    - INGESTION_ACCEPTANCE_TEST_PERSONAL_API_KEY
    - INGESTION_ACCEPTANCE_TEST_EVENT_TIMEOUT_SECONDS (optional, default 90)
    - INGESTION_ACCEPTANCE_TEST_POLL_INTERVAL_SECONDS (optional, default 10.0)
    - INGESTION_ACCEPTANCE_TEST_SLACK_WEBHOOK_URL (optional, for Slack notifications)

    Returns:
        Dict containing test results with summary, individual test outcomes,
        and environment information.
    """
    logger.info("Starting ingestion acceptance tests")

    config = Config()

    logger.info(
        "Loaded config",
        api_host=config.api_host,
        project_id=config.project_id,
    )

    posthog_sdk = posthoganalytics.Posthog(
        config.project_api_key,
        host=config.api_host,
        debug=True,
        sync_mode=True,
    )

    tests = discover_tests()
    client = PostHogClient(config, posthog_sdk)
    with ThreadPoolExecutor() as executor:
        result: TestSuiteResult = await asyncio.to_thread(run_tests, config, tests, client, executor)

    logger.info(
        "Ingestion acceptance tests completed",
        total=result.total_count,
        passed=result.passed_count,
        failed=result.failed_count,
        errors=result.error_count,
        success=result.success,
    )

    send_slack_notification(config, result)

    return result.to_dict()
