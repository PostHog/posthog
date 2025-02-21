from dagster import (
    Definitions,
    load_assets_from_modules,
    run_status_sensor,
    ScheduleDefinition,
    RunRequest,
    DagsterRunStatus,
)
from dagster_aws.s3.io_manager import s3_pickle_io_manager
from dagster_aws.s3.resources import s3_resource
from dagster import fs_io_manager
from django.conf import settings

from . import ch_examples, deletes, orm_examples
from .common import ClickhouseClusterResource
from .materialized_columns import materialize_column
from .person_overrides import squash_person_overrides, cleanup_orphaned_person_overrides_snapshot

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
    job=squash_person_overrides,
    cron_schedule="0 22 * * 6",  # At 22:00 (10 PM) on Saturday
    execution_timezone="UTC",
    name="squash_person_overrides_schedule",
)


@run_status_sensor(
    run_status=DagsterRunStatus.SUCCESS, monitored_jobs=[squash_person_overrides], request_job=deletes.deletes_job
)
def run_deletes_after_squash(context):
    return RunRequest(run_key=None)


defs = Definitions(
    assets=all_assets,
    jobs=[
        cleanup_orphaned_person_overrides_snapshot,
        squash_person_overrides,
        deletes.deletes_job,
        materialize_column,
    ],
    schedules=[squash_schedule],
    sensors=[run_deletes_after_squash],
    resources=resources,
)
