from dagster import Definitions, load_assets_from_modules

from . import ch_examples, deletes, orm_examples

all_assets = load_assets_from_modules([ch_examples, deletes, orm_examples])

defs = Definitions(
    assets=all_assets,
)
