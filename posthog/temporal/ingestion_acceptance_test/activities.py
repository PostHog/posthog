"""Activities for ingestion acceptance test workflow."""

import asyncio
from concurrent.futures import ThreadPoolExecutor

from django.conf import settings

import structlog
import posthoganalytics
import temporalio.activity

from posthog.temporal.ingestion_acceptance_test.client import PostHogClient
from posthog.temporal.ingestion_acceptance_test.config import load_config
from posthog.temporal.ingestion_acceptance_test.results import TestSuiteResult
from posthog.temporal.ingestion_acceptance_test.runner import RunningTests, run_tests
from posthog.temporal.ingestion_acceptance_test.slack import (
    RunContext,
    send_slack_notification,
    send_slack_timeout_notification,
)
from posthog.temporal.ingestion_acceptance_test.test_cases_discovery import discover_tests
from posthog.temporal.ingestion_acceptance_test.types import IngestionAcceptanceTestInput

logger = structlog.get_logger(__name__)


def _current_run_context() -> RunContext | None:
    if not temporalio.activity.in_activity():
        return None
    info = temporalio.activity.info()
    if not (info.workflow_id and info.workflow_run_id and info.workflow_namespace):
        return None
    return RunContext(
        workflow_id=info.workflow_id,
        workflow_run_id=info.workflow_run_id,
        namespace=info.workflow_namespace,
        temporal_ui_host=settings.TEMPORAL_UI_HOST,
    )


@temporalio.activity.defn
async def run_ingestion_acceptance_tests(inputs: IngestionAcceptanceTestInput) -> dict:
    """Run ingestion acceptance tests and return results.

    The lane on the input selects which ingestion routing to target. Config is
    loaded from environment variables:
    - With a lane: INGESTION_ACCEPTANCE_TEST_LANE_<LANE>_{API_HOST,TEAM_ID,PROJECT_API_KEY}
    - Without a lane: the flat INGESTION_ACCEPTANCE_TEST_{API_HOST,PROJECT_API_KEY,TEAM_ID}

    Shared settings come from the flat env vars regardless of lane:
    - INGESTION_ACCEPTANCE_TEST_EVENT_TIMEOUT_SECONDS (optional, default 3600)
    - INGESTION_ACCEPTANCE_TEST_POLL_INTERVAL_SECONDS (optional, default 10.0)
    - INGESTION_ACCEPTANCE_TEST_ACTIVITY_TIMEOUT_SECONDS (optional, default 3600)
    - INGESTION_ACCEPTANCE_TEST_SLACK_WEBHOOK_URL (optional, for Slack notifications)
    - INGESTION_ACCEPTANCE_TEST_ENVIRONMENT, _GRAFANA_URL, _LOKI_DATASOURCE_UID,
      _RUNBOOK_URL (optional, enrich the Slack notification with links)

    Returns:
        Dict containing test results with summary, individual test outcomes,
        and environment information.
    """
    logger.info("Starting ingestion acceptance tests", lane=inputs.lane)

    config = load_config(inputs.lane)

    logger.info(
        "Loaded config",
        api_host=config.api_host,
        team_id=config.team_id,
        lane=config.lane,
    )

    posthog_sdk = posthoganalytics.Posthog(
        config.project_api_key,
        host=config.api_host,
        debug=True,
        sync_mode=True,
    )

    run_context = _current_run_context()
    tests = discover_tests()
    client = PostHogClient(config, posthog_sdk)
    running_tests = RunningTests()
    executor = ThreadPoolExecutor()
    try:
        result: TestSuiteResult = await asyncio.wait_for(
            asyncio.to_thread(run_tests, config, tests, client, executor, running_tests),
            timeout=config.activity_timeout_seconds,
        )
    except TimeoutError:
        still_running = running_tests.snapshot_with_polls(client)
        send_slack_timeout_notification(config, running_tests=still_running, run_context=run_context)
        raise
    finally:
        executor.shutdown(wait=False, cancel_futures=True)

    logger.info(
        "Ingestion acceptance tests completed",
        total=result.total_count,
        passed=result.passed_count,
        failed=result.failed_count,
        errors=result.error_count,
        success=result.success,
    )

    send_slack_notification(config, result, run_context=run_context)

    return result.to_dict()
