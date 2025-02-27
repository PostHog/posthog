import dagster

from dagster_aws.s3.io_manager import s3_pickle_io_manager
from dagster_aws.s3.resources import s3_resource
from django.conf import settings

from . import ch_examples, deletes, exchange_rate, materialized_columns, orm_examples, person_overrides
from .common import ClickhouseClusterResource

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
        "io_manager": dagster.fs_io_manager,
    },
}


# Get resources for current environment, fallback to local if env not found
resources = resources_by_env.get(env, resources_by_env["local"])

defs = dagster.Definitions(
    assets=dagster.load_assets_from_modules([ch_examples, orm_examples, exchange_rate, materialized_columns]),
    jobs=[
        deletes.deletes_job,
        exchange_rate.daily_exchange_rates_job,
        exchange_rate.hourly_exchange_rates_job,
        materialized_columns.materialize_column,
        person_overrides.cleanup_orphaned_person_overrides_snapshot,
        person_overrides.squash_person_overrides,
    ],
    schedules=[
        person_overrides.squash_schedule,
        exchange_rate.daily_exchange_rates_schedule,
        exchange_rate.hourly_exchange_rates_schedule,
    ],
    sensors=[person_overrides.run_deletes_after_squash],
    resources=resources,
)

if settings.DEBUG:
    from . import testing

    defs.jobs.append(testing.error)
