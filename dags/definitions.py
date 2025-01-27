from dagster import Definitions, load_assets_from_modules
from dagster_aws.s3.io_manager import s3_pickle_io_manager
from dagster_aws.s3.resources import s3_resource
from dagster import fs_io_manager
from django.conf import settings

from . import ch_examples, deletes, orm_examples
from .person_overrides import ClickhouseClusterResource, squash_person_overrides

all_assets = load_assets_from_modules([ch_examples, deletes, orm_examples])

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
    jobs=[squash_person_overrides],
    resources=resources,
)
