import json
import dataclasses
from datetime import UTC, datetime, timedelta

import structlog
from temporalio import common, workflow

from posthog.temporal.common.base import PostHogWorkflow

with workflow.unsafe.imports_passed_through():
    from posthog.temporal.npm_release_monitor.activities import (
        CorrelateReleasesInput,
        FetchGitHubWorkflowRunsInput,
        FetchNpmVersionsInput,
        SendAlertsInput,
        correlate_releases,
        fetch_github_workflow_runs,
        fetch_npm_versions,
        send_alerts,
    )
    from posthog.temporal.npm_release_monitor.config import MONITORED_PACKAGES, get_packages_by_repo

logger = structlog.get_logger(__name__)


@dataclasses.dataclass
class NpmReleaseMonitorInputs:
    lookback_hours: int = 1
    github_token: str | None = None
    slack_webhook_url: str | None = None
    incident_io_api_key: str | None = None


@workflow.defn(name="npm-release-monitor")
class NpmReleaseMonitorWorkflow(PostHogWorkflow):
    """
    Temporal workflow that monitors npm releases for PostHog packages
    and alerts if releases don't correlate with CI/CD runs.

    This workflow:
    1. Fetches recent npm publishes for monitored packages
    2. Fetches GitHub workflow runs from corresponding repos
    3. Correlates npm publishes with CI/CD runs
    4. Alerts on any releases that appear unauthorized
    """

    @staticmethod
    def parse_inputs(inputs: list[str]) -> NpmReleaseMonitorInputs:
        """Parse inputs from the management command CLI."""
        if inputs:
            loaded = json.loads(inputs[0])
            return NpmReleaseMonitorInputs(**loaded)
        return NpmReleaseMonitorInputs()

    @workflow.run
    async def run(self, inputs: NpmReleaseMonitorInputs) -> dict:
        """Execute the npm release monitoring workflow."""
        logger.info(
            "Starting npm release monitor workflow",
            lookback_hours=inputs.lookback_hours,
            num_packages=len(MONITORED_PACKAGES),
        )

        since_timestamp = (datetime.now(UTC) - timedelta(hours=inputs.lookback_hours)).isoformat()

        packages = [p.npm_package for p in MONITORED_PACKAGES]
        npm_result = await workflow.execute_activity(
            fetch_npm_versions,
            FetchNpmVersionsInput(packages=packages, since_timestamp=since_timestamp),
            start_to_close_timeout=timedelta(minutes=10),
            retry_policy=common.RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=30)),
        )

        if not npm_result.versions:
            logger.info("No new npm versions found in lookback window")
            return {
                "status": "ok",
                "message": "No new versions to check",
                "npm_errors": npm_result.errors,
            }

        logger.info("Found npm versions to check", count=len(npm_result.versions))

        repos = list(get_packages_by_repo().keys())
        github_result = await workflow.execute_activity(
            fetch_github_workflow_runs,
            FetchGitHubWorkflowRunsInput(
                repos=repos,
                since_timestamp=since_timestamp,
                github_token=inputs.github_token,
            ),
            start_to_close_timeout=timedelta(minutes=10),
            retry_policy=common.RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=30)),
        )

        logger.info("Fetched GitHub workflow runs", count=len(github_result.runs))

        packages_config = [
            {
                "npm_package": p.npm_package,
                "github_repo": p.github_repo,
                "workflow_names": p.workflow_names,
                "time_window_minutes": p.time_window_minutes,
            }
            for p in MONITORED_PACKAGES
        ]

        correlation_result = await workflow.execute_activity(
            correlate_releases,
            CorrelateReleasesInput(
                npm_versions=npm_result.versions,
                github_runs=github_result.runs,
                packages_config=packages_config,
            ),
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=common.RetryPolicy(maximum_attempts=2),
        )

        logger.info(
            "Correlation complete",
            unauthorized=len(correlation_result.unauthorized_releases),
            correlated=len(correlation_result.correlated_releases),
        )

        if correlation_result.unauthorized_releases:
            alert_result = await workflow.execute_activity(
                send_alerts,
                SendAlertsInput(
                    unauthorized_releases=correlation_result.unauthorized_releases,
                    slack_webhook_url=inputs.slack_webhook_url,
                    incident_io_api_key=inputs.incident_io_api_key,
                ),
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=common.RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=10)),
            )

            return {
                "status": "alert",
                "message": f"Found {len(correlation_result.unauthorized_releases)} unauthorized releases",
                "unauthorized_releases": correlation_result.unauthorized_releases,
                "correlated_releases": correlation_result.correlated_releases,
                "alerts_sent": alert_result.alerts_sent,
                "incidents_created": alert_result.incidents_created,
                "alert_errors": alert_result.errors,
                "npm_errors": npm_result.errors,
                "github_errors": github_result.errors,
            }

        return {
            "status": "ok",
            "message": f"All {len(correlation_result.correlated_releases)} releases correlated with CI/CD",
            "correlated_releases": correlation_result.correlated_releases,
            "npm_errors": npm_result.errors,
            "github_errors": github_result.errors,
        }
