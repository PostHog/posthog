from dagster import Definitions, load_assets_from_modules

from . import assets, deletes

all_assets = load_assets_from_modules([assets, deletes])

defs = Definitions(
    assets=all_assets,
)
