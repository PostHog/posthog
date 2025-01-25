from dagster import Definitions, load_assets_from_modules, ScheduleDefinition

from . import ch_examples, orm_examples
from .deletes import deletes_job
from .person_overrides import ClickhouseClusterResource, squash_person_overrides

all_assets = load_assets_from_modules([ch_examples, orm_examples])

# Schedule to run deletes at 10 PM on Saturdays
deletes_schedule = ScheduleDefinition(
    job=deletes_job,
    cron_schedule="0 22 * * 6",  # At 22:00 (10 PM) on Saturday
    execution_timezone="UTC",
    name="deletes_schedule",
)
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

defs = Definitions(
    assets=all_assets,
    jobs=[squash_person_overrides, deletes_job],
    schedules=[deletes_schedule],
    resources={
        "cluster": ClickhouseClusterResource.configure_at_launch(),
    },
)
