from dagster import Definitions, load_assets_from_modules

from . import ch_examples, deletes

all_assets = load_assets_from_modules([ch_examples, deletes])

defs = Definitions(
    assets=all_assets,
)
