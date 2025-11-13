"""Dagster Slack alerts for job failures.

This module implements intelligent alert routing for Dagster job failures. For most jobs,
alerts are sent to the team's Slack channel based on the job's owner tag. However, the
special case is __ASSET_JOB, which is Dagster's dynamically-created job for ad hoc
materializations triggered from the UI. Since __ASSET_JOB can contain assets from multiple
teams, we parse the error message to extract failed asset names and route alerts to each
affected team separately.

See: https://github.com/dagster-io/dagster/discussions/18819#discussioncomment-7909153
"""

import re
from collections import defaultdict

from django.conf import settings

import dagster
import dagster_slack
from dagster import DagsterRunStatus, RunsFilter

from dags.common import JobOwners

# Constants
ASSET_JOB_NAME = "__ASSET_JOB"
DEFAULT_OWNER = "unknown"
DEFAULT_ENVIRONMENT = "unknown"

# Regex patterns for parsing error messages
STEPS_FAILED_PATTERN = r"Steps failed:.*?\[([^\]]+)\]"
STEP_NAME_PATTERN = r"'([^']+)'"

# Alert message templates
ALERT_EMOJI = "❌"
ALERT_HEADER_ASSET_JOB = "Ad hoc materialization failed"
ALERT_HEADER_NAMED_JOB = "Dagster job `{job_name}` failed"

notification_channel_per_team = {
    JobOwners.TEAM_ANALYTICS_PLATFORM.value: "#alerts-analytics-platform",
    JobOwners.TEAM_CLICKHOUSE.value: "#alerts-clickhouse",
    JobOwners.TEAM_DATA_WAREHOUSE.value: "#alerts-data-warehouse",
    JobOwners.TEAM_ERROR_TRACKING.value: "#alerts-error-tracking",
    JobOwners.TEAM_EXPERIMENTS.value: "#alerts-experiments",
    JobOwners.TEAM_GROWTH.value: "#alerts-growth",
    JobOwners.TEAM_MAX_AI.value: "#alerts-max-ai",
    JobOwners.TEAM_REVENUE_ANALYTICS.value: "#alerts-revenue-analytics",
    JobOwners.TEAM_WEB_ANALYTICS.value: "#alerts-web-analytics",
}

# Asset name -> owner tag registry, populated at initialization
ASSET_OWNER_REGISTRY: dict[str, str] = {}

CONSECUTIVE_FAILURE_THRESHOLDS: dict[str, int] = {
    "web_pre_aggregate_current_day_hourly_job": 3,
    "web_pre_aggregate_job": 3,
    "web_pre_aggregate_daily_job": 3,
}


def build_asset_owner_registry(context: dagster.RunFailureSensorContext) -> None:
    """Build a registry mapping asset names to their owner tags from the current repository.

    Note: This builds the registry from assets in the current repository only. With
    monitor_all_code_locations=True on the sensor, the context will include runs from all
    locations, but we can only access asset definitions from the repository where this
    sensor is defined.
    """
    global ASSET_OWNER_REGISTRY

    if ASSET_OWNER_REGISTRY:
        return

    try:
        # Get all asset definitions from the repository
        assets_by_key = context.repository_def.assets_defs_by_key

        for asset_key, asset_def in assets_by_key.items():
            owner = asset_def.tags.get("owner", DEFAULT_OWNER)
            ASSET_OWNER_REGISTRY[asset_key.to_user_string()] = owner

        context.log.info(f"Built asset owner registry with {len(ASSET_OWNER_REGISTRY)} assets")
    except Exception as e:
        context.log.exception(f"Failed to build asset owner registry: {str(e)}")


def get_failed_steps_by_owner(error_message: str) -> dict[str, list[str]]:
    """Extract failed asset names from error message and group by owner.

    Returns a dict mapping owner tag to list of failed asset names for that owner.
    """
    match = re.search(STEPS_FAILED_PATTERN, error_message)

    if not match:
        return {}

    steps_text = match.group(1)
    step_names = re.findall(STEP_NAME_PATTERN, steps_text)

    # Group failed steps by owner
    steps_by_owner = defaultdict(list)
    for step_name in step_names:
        owner = ASSET_OWNER_REGISTRY.get(step_name, DEFAULT_OWNER)
        steps_by_owner[owner].append(step_name)

    return dict(steps_by_owner)


def get_owners_for_failed_job(failed_run: dagster.DagsterRun, error_message: str) -> dict[str, list[str]]:
    """Determine which owners should receive alerts for this job failure.

    Returns dict mapping owner -> list of failed asset names:
    - For named jobs: {owner: []} - single owner, empty asset list (whole job failed)
    - For __ASSET_JOB: {owner1: [asset1, asset2], owner2: [asset3]} - grouped by owner
    """
    if failed_run.job_name == ASSET_JOB_NAME:
        return get_failed_steps_by_owner(error_message)
    else:
        # Named job - use owner tag from run, no specific assets
        owner = failed_run.tags.get("owner", DEFAULT_OWNER)
        return {owner: []}  # Empty list indicates this is a named job (no specific assets)


def should_suppress_alert(context: dagster.RunFailureSensorContext, job_name: str, threshold: int) -> bool:
    """Check if an alert should be suppressed based on consecutive failure threshold.

    Returns True if the alert should be suppressed, False if it should be sent.
    """
    if threshold < 1:
        context.log.warning(f"Invalid threshold {threshold} for job {job_name}, must be >= 1. Sending alert.")
        return False

    try:
        run_records = context.instance.get_run_records(
            RunsFilter(
                job_name=job_name,
            ),
            limit=threshold,
        )

        if len(run_records) < threshold:
            context.log.info(
                f"Job {job_name} has {len(run_records)} run(s), suppressing alert until {threshold} consecutive failures"
            )
            return True

        all_failed = all(record.dagster_run.status == DagsterRunStatus.FAILURE for record in run_records)

        if all_failed:
            context.log.warning(f"Job {job_name} has {threshold} consecutive failures, sending alert")
            return False
        else:
            context.log.info(f"Job {job_name} does not have {threshold} consecutive failures, suppressing alert")
            return True

    except Exception as e:
        # If we fail to check run history, err on the side of sending the alert
        context.log.exception(f"Failed to check consecutive failures for {job_name}: {str(e)}")
        return False


def send_failure_notification(
    context: dagster.RunFailureSensorContext,
    slack: dagster_slack.SlackResource,
    job_name: str,
    run_id: str,
    error: str,
    owner: str,
    tags: dict[str, str],
    failed_assets: list[str] | None = None,
) -> None:
    """Send a single failure notification to a team's Slack channel."""
    dagster_domain = settings.DAGSTER_DOMAIN if settings.DAGSTER_DOMAIN else "dagster.localhost"
    run_url = f"https://{dagster_domain}/runs/{run_id}"

    environment = (
        f"{settings.CLOUD_DEPLOYMENT} :flag-{settings.CLOUD_DEPLOYMENT}:"
        if settings.CLOUD_DEPLOYMENT
        else DEFAULT_ENVIRONMENT
    )

    # Build message header
    if failed_assets:
        asset_list = ", ".join(f"`{asset}`" for asset in failed_assets)
        header = f"{ALERT_EMOJI} *{ALERT_HEADER_ASSET_JOB}*\n\n*Failed assets*: {asset_list}"
    else:
        header = f"{ALERT_EMOJI} *{ALERT_HEADER_NAMED_JOB.format(job_name=job_name)}*"

    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"{header}\n\n*Run ID*: `{run_id}`\n*Run URL*: <{run_url}|View in Dagster>\n*Tags*: {tags}",
            },
        },
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*Error*:\n```{error}```"}},
        {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": f"Environment: {environment}"}],
        },
    ]

    try:
        slack.get_client().chat_postMessage(
            channel=notification_channel_per_team.get(owner, settings.DAGSTER_DEFAULT_SLACK_ALERTS_CHANNEL),
            blocks=blocks,
        )
        context.log.info(f"Sent Slack notification for failed job {job_name} to {owner} team")
    except Exception as e:
        context.log.exception(f"Failed to send Slack notification: {str(e)}")


@dagster.run_failure_sensor(default_status=dagster.DefaultSensorStatus.RUNNING, monitor_all_code_locations=True)
def notify_slack_on_failure(context: dagster.RunFailureSensorContext, slack: dagster_slack.SlackResource):
    """Send a notification to Slack when any job fails."""
    failed_run = context.dagster_run
    job_name = failed_run.job_name
    run_id = failed_run.run_id
    error = context.failure_event.message if context.failure_event.message else "Unknown error"
    tags = failed_run.tags

    # Only send notifications in prod environment
    if not settings.CLOUD_DEPLOYMENT:
        context.log.info("Skipping Slack notification in non-prod environment")
        return

    if tags.get("disable_slack_notifications"):
        context.log.debug("Skipping Slack notification for %s, notifications are disabled", job_name)
        return

    # Check if this job has a consecutive failure threshold configured
    threshold = CONSECUTIVE_FAILURE_THRESHOLDS.get(job_name, 1)
    if threshold > 1:
        if should_suppress_alert(context, job_name, threshold):
            return

    # Build asset owner registry for __ASSET_JOB (no-op for named jobs)
    if job_name == ASSET_JOB_NAME:
        build_asset_owner_registry(context)

    # Get owners and failed assets for this job
    owners_and_assets = get_owners_for_failed_job(failed_run, error)

    if not owners_and_assets:
        # No owners identified (shouldn't happen, but handle gracefully)
        context.log.warning(f"No owners identified for failed job {job_name}")
        return

    # Send notification to each affected team
    for owner, failed_assets in owners_and_assets.items():
        send_failure_notification(
            context=context,
            slack=slack,
            job_name=job_name,
            run_id=run_id,
            error=error,
            owner=owner,
            tags=tags,
            failed_assets=failed_assets if failed_assets else None,
        )
