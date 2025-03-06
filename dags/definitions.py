from dagster import (
    DagsterRunStatus,
    Definitions,
    EnvVar,
    ResourceDefinition,
    RunRequest,
    ScheduleDefinition,
    fs_io_manager,
    load_assets_from_modules,
    run_status_sensor,
)
from dagster_aws.s3.io_manager import s3_pickle_io_manager
from dagster_aws.s3 import S3Resource
from dagster_slack import SlackResource
from django.conf import settings

from dags import backup_database
from dags.slack_alerts import notify_slack_on_failure

from . import ch_examples, deletes, materialized_columns, orm_examples, person_overrides, export_query_logs_to_s3
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
        "s3": S3Resource(),
        # Using EnvVar instead of the Django setting to ensure that the token is not leaked anywhere in the Dagster UI
        "slack": SlackResource(token=EnvVar("SLACK_TOKEN")),
    },
    "local": {
        "cluster": ClickhouseClusterResource.configure_at_launch(),
        "io_manager": fs_io_manager,
        "s3": S3Resource(),
        "slack": ResourceDefinition.none_resource(description="Dummy Slack resource for local development"),
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

# Schedule to run query logs export at 1 AM daily
query_logs_export_schedule = ScheduleDefinition(
    job=export_query_logs_to_s3.export_query_logs_to_s3,
    cron_schedule="0 1 * * *",  # At 01:00 (1 AM) every day
    execution_timezone="UTC",
    name="query_logs_export_schedule",
)


@run_status_sensor(
    run_status=DagsterRunStatus.SUCCESS,
    monitored_jobs=[person_overrides.squash_person_overrides],
    request_job=deletes.deletes_job,
)
def run_deletes_after_squash(context):
    return RunRequest(run_key=None)


defs = Definitions(
    assets=all_assets,
    jobs=[
        deletes.deletes_job,
        materialized_columns.materialize_column,
        person_overrides.cleanup_orphaned_person_overrides_snapshot,
        person_overrides.squash_person_overrides,
        export_query_logs_to_s3.export_query_logs_to_s3,
        backup_database.backup_database,
    ],
    schedules=[squash_schedule, query_logs_export_schedule],
    sensors=[run_deletes_after_squash, notify_slack_on_failure],
    resources=resources,
)

if settings.DEBUG:
    from . import testing

    defs.jobs.append(testing.error)
