import dagster
import dagster_slack
import re

from django.conf import settings

from dags.common import JobOwners

notification_channel_per_team = {
    JobOwners.TEAM_CLICKHOUSE.value: "#alerts-clickhouse",
    JobOwners.TEAM_WEB_ANALYTICS.value: "#alerts-web-analytics",
    JobOwners.TEAM_REVENUE_ANALYTICS.value: "#alerts-revenue-analytics",
    JobOwners.TEAM_ERROR_TRACKING.value: "#alerts-error-tracking",
}


def get_job_owner_for_alert(failed_run: dagster.DagsterRun, error_message: str) -> str:
    """Determine the correct job owner for alert routing, with special handling for asset jobs."""
    job_name = failed_run.job_name
    job_owner = failed_run.tags.get("owner", "unknown")

    # Special handling for manually launched asset jobs
    if job_name == "__ASSET_JOB":
        # Check if the error message contains web_ prefixed failed steps
        # Pattern: "Steps failed: ['web_analytics_bounces_hourly', 'web_analytics_stats_table_hourly']"
        web_step_pattern = r"Steps failed:.*?\[([^\]]+)\]"
        match = re.search(web_step_pattern, error_message)

        if match:
            steps_text = match.group(1)
            # Check if any step starts with 'web_'
            if re.search(r"'web_[^']*'", steps_text):
                return JobOwners.TEAM_WEB_ANALYTICS.value

    return job_owner


@dagster.run_failure_sensor(default_status=dagster.DefaultSensorStatus.RUNNING)
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

    # Construct Dagster URL based on environment
    dagster_domain = (
        f"dagster.prod-{settings.CLOUD_DEPLOYMENT.lower()}.posthog.dev"
        if settings.CLOUD_DEPLOYMENT
        else "dagster.localhost"
    )
    run_url = f"https://{dagster_domain}/runs/{run_id}"

    environment = (
        f"{settings.CLOUD_DEPLOYMENT} :flag-{settings.CLOUD_DEPLOYMENT}:" if settings.CLOUD_DEPLOYMENT else "unknown"
    )
    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"❌ *Dagster job `{job_name}` failed*\n\n*Run ID*: `{run_id}`\n*Run URL*: <{run_url}|View in Dagster>\n*Tags*: {tags}",
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
            channel=notification_channel_per_team.get(job_owner, settings.DAGSTER_DEFAULT_SLACK_ALERTS_CHANNEL),
            blocks=blocks,
        )
        context.log.info(f"Sent Slack notification for failed job {job_name} to {job_owner} team")
    except Exception as e:
        context.log.exception(f"Failed to send Slack notification: {str(e)}")
