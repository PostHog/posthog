"""Activities for ingestion acceptance test workflow."""

import structlog
import temporalio.activity

from posthog.temporal.ingestion_acceptance_test.results import TestSuiteResult
from posthog.temporal.ingestion_acceptance_test.runner import run_tests

logger = structlog.get_logger(__name__)


@temporalio.activity.defn
async def run_ingestion_acceptance_tests() -> dict:
    """Run ingestion acceptance tests and return results.

    Configuration is loaded from environment variables:
    - INGESTION_ACCEPTANCE_TEST_API_HOST
    - INGESTION_ACCEPTANCE_TEST_PROJECT_API_KEY
    - INGESTION_ACCEPTANCE_TEST_PROJECT_ID
    - INGESTION_ACCEPTANCE_TEST_PERSONAL_API_KEY
    - INGESTION_ACCEPTANCE_TEST_EVENT_TIMEOUT_SECONDS (optional, default 30)
    - INGESTION_ACCEPTANCE_TEST_POLL_INTERVAL_SECONDS (optional, default 2.0)
    - INGESTION_ACCEPTANCE_TEST_SLACK_WEBHOOK_URL (optional, for Slack notifications)

    Returns:
        Dict containing test results with summary, individual test outcomes,
        and environment information.
    """
    logger.info("Starting ingestion acceptance tests")

    result: TestSuiteResult = run_tests()

    logger.info(
        "Ingestion acceptance tests completed",
        total=result.total_count,
        passed=result.passed_count,
        failed=result.failed_count,
        errors=result.error_count,
        success=result.success,
    )

    return result.to_dict()
