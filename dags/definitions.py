from dagster import Definitions, load_assets_from_modules
from dagster_aws.s3.io_manager import s3_pickle_io_manager
from dagster_aws.s3.resources import s3_resource

from . import ch_examples, deletes, orm_examples
from .person_overrides import ClickhouseClusterResource, squash_person_overrides

all_assets = load_assets_from_modules([ch_examples, deletes, orm_examples])

defs = Definitions(
    assets=all_assets,
    resources={
         "cluster": ClickhouseClusterResource.configure_at_launch(),
        "io_manager": s3_pickle_io_manager.configured({"s3_bucket": "posthog-dags", "s3_prefix": "dag-storage"}),
        "s3": s3_resource,
    jobs=[squash_person_overrides],
)
