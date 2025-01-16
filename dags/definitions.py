from dagster import Definitions, load_assets_from_modules

from . import deletes

all_assets = load_assets_from_modules([deletes])

defs = Definitions(
    assets=all_assets,
)
