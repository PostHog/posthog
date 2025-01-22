from dagster import Definitions, load_assets_from_modules

from . import ch_examples, deletes, orm_examples
from .person_overrides import ClickhouseClusterResource, squash_person_overrides

all_assets = load_assets_from_modules([ch_examples, deletes, orm_examples])

defs = Definitions(
    assets=all_assets,
    jobs=[squash_person_overrides],
    resources={
        "cluster": ClickhouseClusterResource.configure_at_launch(),
    },
)
