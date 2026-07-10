import re

from django.conf import settings

import dagster
import dagster_slack
from dagster import DagsterRunStatus, RunsFilter
from slack_sdk.errors import SlackApiError

from posthog.dags.common import JobOwners

notification_channel_per_team = {
    JobOwners.TEAM_ANALYTICS_PLATFORM.value: "#alerts-analytics-platform",
    JobOwners.TEAM_BILLING.value: "#alerts-billing",
    JobOwners.TEAM_CLICKHOUSE.value: "#alerts-clickhouse",
    JobOwners.TEAM_DATA_MODELING.value: "#alerts-data-modeling",
    JobOwners.TEAM_DATA_STACK.value: "#alerts-data-warehouse",
    JobOwners.TEAM_DATA_TOOLS.value: "#alerts-data-tools",
    JobOwners.TEAM_ERROR_TRACKING.value: "#alerts-error-tracking",
    JobOwners.TEAM_GROWTH.value: "#alerts-growth",
    JobOwners.TEAM_AI_OBSERVABILITY.value: "#alerts-aio",
    JobOwners.TEAM_MANAGED_WAREHOUSE.value: "#alerts-managed-warehouse",
    JobOwners.TEAM_INGESTION.value: "#alerts-ingestion",
    JobOwners.TEAM_LOGS.value: "#alerts-logs-prod",
    JobOwners.TEAM_POSTHOG_AI.value: "#alerts-max-ai",
    JobOwners.TEAM_QUERY_PERFORMANCE.value: "#alerts-query-performance",
    JobOwners.TEAM_SECURITY.value: "#alerts-security",
    JobOwners.TEAM_WAREHOUSE_SOURCES.value: "#alerts-warehouse-sources",
    JobOwners.TEAM_WEB_ANALYTICS.value: "#alerts-web-analytics",
}

CONSECUTIVE_FAILURE_THRESHOLDS = {
    "web_pre_aggregate_current_day_hourly_job": 3,
    "web_pre_aggregate_job": 3,
    "web_pre_aggregate_daily_job": 3,
}

# Slack rejects the entire message with `invalid_blocks` if any section's text exceeds 3000 chars,
# so keep each field comfortably under that limit (leaving headroom for surrounding markdown/fences).
SLACK_SECTION_TEXT_LIMIT = 3000


def _truncate_for_slack(text: str, limit: int) -> str:
    """Truncate text to fit inside a Slack section block.

    A verbose failure (e.g. a Kubernetes or ClickHouse API exception) would otherwise blow past
    Slack's 3000-char section limit and cause the whole notification to be silently dropped. Keep
    the head and tail so both the top of the error and its root cause survive.
    """
    if len(text) <= limit:
        return text
    marker = "\n…(truncated)…\n"
    keep = max(limit - len(marker), 0)
    head = keep * 2 // 3
    tail = keep - head
    return f"{text[:head]}{marker}{text[-tail:]}" if tail else f"{text[:head]}{marker}"


# Slack API error codes that mean the block payload itself was rejected, so the message was NOT
# posted and a plain-text retry is safe. Any other failure (network, rate limit, a raise while
# reading the response) is ambiguous — the blocks may have posted, so retrying there would double up.
SLACK_BLOCK_REJECTION_ERRORS = frozenset(
    {"invalid_blocks", "invalid_blocks_format", "blocks_too_long", "msg_too_long", "metadata_too_large"}
)


def send_slack_alert(context, client, channel: str, blocks: list, fallback_text: str) -> None:
    """Post an alert, falling back to a plain-text message if the rich blocks are rejected.

    A block-formatting or size error (e.g. an oversized error field exceeding Slack's 3000-char
    section limit) previously suppressed the alert entirely because the exception was only logged.
    Retry text-only when Slack rejected the blocks outright so a run failure can't go silently
    un-alerted, but only then — retrying on an ambiguous failure risks posting the alert twice.
    """
    try:
        client.chat_postMessage(channel=channel, blocks=blocks, text=fallback_text)
        context.log.info(f"Sent Slack notification to {channel}")
        return
    except SlackApiError as e:
        error_code = e.response.get("error") if e.response is not None else None
        if error_code not in SLACK_BLOCK_REJECTION_ERRORS:
            # The message may have posted (rate limit, transient read error, ...) — don't duplicate it.
            context.log.exception(f"Failed to send Slack notification to {channel}: {str(e)}")
            return
        context.log.warning(f"Slack rejected blocks ({error_code}) for {channel}, retrying text-only")
    except Exception as e:
        # Non-API failure: the outcome is ambiguous, so log and stop rather than risk a duplicate.
        context.log.exception(f"Failed to send Slack notification to {channel}: {str(e)}")
        return

    try:
        client.chat_postMessage(channel=channel, text=fallback_text)
        context.log.info(f"Sent text-only Slack fallback to {channel}")
    except Exception as e:
        context.log.exception(f"Failed to send text-only Slack fallback to {channel}: {str(e)}")


def get_job_owner_for_alert(failed_run: dagster.DagsterRun, error_message: str) -> str:
    """Determine the correct job owner for alert routing, with special handling for asset jobs."""
    job_name = failed_run.job_name
    job_owner = failed_run.tags.get("owner", "unknown")

    # Special handling for manually launched asset jobs
    if job_name == "__ASSET_JOB":
        # Check if the error message contains web_ prefixed failed steps
        # Pattern: "Steps failed: ['web_pre_aggregated_bounces', 'web_pre_aggregated_stats']"
        web_step_pattern = r"Steps failed:.*?\[([^\]]+)\]"
        match = re.search(web_step_pattern, error_message)

        if match:
            steps_text = match.group(1)
            # Check if any step starts with 'web_'
            if re.search(r"'web_[^']*'", steps_text):
                return JobOwners.TEAM_WEB_ANALYTICS.value

    return job_owner


def should_suppress_alert(context: dagster.RunFailureSensorContext, job_name: str, threshold: int) -> bool:
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


@dagster.run_failure_sensor(default_status=dagster.DefaultSensorStatus.RUNNING, monitor_all_code_locations=True)
def notify_slack_on_failure(context: dagster.RunFailureSensorContext, slack: dagster_slack.SlackResource):
    """Send a notification to Slack when any job fails."""
    # Get the failed run
    failed_run = context.dagster_run
    job_name = failed_run.job_name
    run_id = failed_run.run_id
    error = context.failure_event.message if context.failure_event.message else "Unknown error"
    job_owner = get_job_owner_for_alert(failed_run, error)
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

    # Construct Dagster URL based on environment
    dagster_domain = settings.DAGSTER_DOMAIN if settings.DAGSTER_DOMAIN else "dagster.localhost"
    run_url = f"https://{dagster_domain}/runs/{run_id}"

    environment = (
        f"{settings.CLOUD_DEPLOYMENT} :flag-{settings.CLOUD_DEPLOYMENT}:" if settings.CLOUD_DEPLOYMENT else "unknown"
    )

    channel = notification_channel_per_team.get(job_owner, settings.DAGSTER_DEFAULT_SLACK_ALERTS_CHANNEL)

    # Truncate so a single oversized field can't get the whole message rejected. The error is wrapped
    # in a ``` code fence, so leave headroom below the 3000-char section limit for the fence + label.
    tags_text = _truncate_for_slack(str(tags), 500)
    error_text = _truncate_for_slack(str(error), SLACK_SECTION_TEXT_LIMIT - 200)

    blocks: list[dict[str, object]] = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"❌ *Dagster job `{job_name}` failed*\n\n*Run ID*: `{run_id}`\n*Run URL*: <{run_url}|View in Dagster>\n*Tags*: {tags_text}",
            },
        },
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*Error*:\n```{error_text}```"}},
        {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": f"Environment: {environment}"}],
        },
    ]

    # Plain-text fallback carried on every message so the alert still lands (and renders in
    # notifications) even if the rich blocks are rejected.
    fallback_text = f"❌ Dagster job `{job_name}` failed (run {run_id}): {run_url}"
    send_slack_alert(context, slack.get_client(), channel, blocks, fallback_text)
