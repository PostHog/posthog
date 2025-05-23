import dagster
import dagster_slack

from django.conf import settings

from dags.common import JobOwners

notification_channel_per_team = {
    JobOwners.TEAM_CLICKHOUSE.value: "#alerts-clickhouse",
    JobOwners.TEAM_WEB_ANALYTICS.value: "#alerts-web-analytics",
    JobOwners.TEAM_REVENUE_ANALYTICS.value: "#alerts-revenue-analytics",
}


@dagster.run_failure_sensor(default_status=dagster.DefaultSensorStatus.RUNNING)
def notify_slack_on_failure(context: dagster.RunFailureSensorContext, slack: dagster_slack.SlackResource):
    """Send a notification to Slack when any job fails."""
    # Get the failed run
    failed_run = context.dagster_run
    job_name = failed_run.job_name
    run_id = failed_run.run_id
    job_owner = failed_run.tags.get("owner", "unknown")
    error = context.failure_event.message if context.failure_event.message else "Unknown error"
    tags = failed_run.tags

    # Only send notifications in prod environment
    if not settings.CLOUD_DEPLOYMENT:
        context.log.info("Skipping Slack notification in non-prod environment")
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
        context.log.info(f"Sent Slack notification for failed job {job_name}")
    except Exception as e:
        context.log.exception(f"Failed to send Slack notification: {str(e)}")
