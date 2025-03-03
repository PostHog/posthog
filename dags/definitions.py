from dagster import (
    DagsterRunStatus,
    Definitions,
    RunRequest,
    ScheduleDefinition,
    fs_io_manager,
    load_assets_from_modules,
    run_status_sensor,
)
from dagster_aws.s3.io_manager import s3_pickle_io_manager
from dagster_aws.s3.resources import s3_resource
from dagster_slack import slack_resource
from django.conf import settings

from . import ch_examples, deletes, materialized_columns, orm_examples, person_overrides
from .common import ClickhouseClusterResource

all_assets = load_assets_from_modules([ch_examples, orm_examples])


env = "local" if settings.DEBUG else "prod"


# Define resources for different environments
resources_by_env = {
    "prod": {
        "cluster": ClickhouseClusterResource.configure_at_launch(),
        "io_manager": s3_pickle_io_manager.configured(
            {"s3_bucket": settings.DAGSTER_S3_BUCKET, "s3_prefix": "dag-storage"}
        ),
        "s3": s3_resource,
        "slack": slack_resource.configured(
            {"token": settings.SLACK_BOT_TOKEN, "default_channel": "#alerts-clickhouse"}
        ),
    },
    "local": {
        "cluster": ClickhouseClusterResource.configure_at_launch(),
        "io_manager": fs_io_manager,
    },
}


# Get resources for current environment, fallback to local if env not found
resources = resources_by_env.get(env, resources_by_env["local"])


# Schedule to run squash at 10 PM on Saturdays
squash_schedule = ScheduleDefinition(
    job=person_overrides.squash_person_overrides,
    cron_schedule="0 22 * * 6",  # At 22:00 (10 PM) on Saturday
    execution_timezone="UTC",
    name="squash_person_overrides_schedule",
)


@run_status_sensor(
    run_status=DagsterRunStatus.SUCCESS,
    monitored_jobs=[person_overrides.squash_person_overrides],
    request_job=deletes.deletes_job,
)
def run_deletes_after_squash(context):
    return RunRequest(run_key=None)


@run_status_sensor(run_status=DagsterRunStatus.FAILURE)
def notify_slack_on_failure(context):
    """Send a notification to Slack when any job fails."""
    # Get the failed run
    failed_run = context.dagster_run
    job_name = failed_run.job_name
    run_id = failed_run.run_id
    error = failed_run.failure_data.error.message if failed_run.failure_data else "Unknown error"

    # Only send notifications in prod environment
    if env != "prod":
        context.log.info("Skipping Slack notification in non-prod environment")
        return

    # Construct Dagster URL based on environment
    dagster_domain = (
        f"dagster.prod-{settings.CLOUD_DEPLOYMENT.lower()}.posthog.dev"
        if settings.CLOUD_DEPLOYMENT
        else "dagster.localhost"
    )
    run_url = f"https://{dagster_domain}/runs/{run_id}"

    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"❌ *DAG Failure Alert*\n*Job*: `{job_name}`\n*Run ID*: `{run_id}`\n*Run URL*: <{run_url}|View in Dagster>",
            },
        },
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*Error*:\n```{error}```"}},
        {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": f"Environment: {settings.CLOUD_DEPLOYMENT or 'unknown'}"}],
        },
    ]

    try:
        # Use Dagster's slack resource
        context.resources.slack.get_client().chat_postMessage(
            channel=context.resources.slack.default_channel, blocks=blocks, text=f"DAG Failure Alert: {job_name} failed"
        )
        context.log.info(f"Sent Slack notification for failed job {job_name}")
    except Exception as e:
        context.log.exception(f"Failed to send Slack notification: {str(e)}")


defs = Definitions(
    assets=all_assets,
    jobs=[
        deletes.deletes_job,
        materialized_columns.materialize_column,
        person_overrides.cleanup_orphaned_person_overrides_snapshot,
        person_overrides.squash_person_overrides,
    ],
    schedules=[squash_schedule],
    sensors=[run_deletes_after_squash, notify_slack_on_failure],
    resources=resources,
)

if settings.DEBUG:
    from . import testing

    defs.jobs.append(testing.error)
