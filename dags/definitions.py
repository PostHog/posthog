from dagster import Definitions, load_assets_from_modules

from . import assets
from .person_overrides import squash_person_overrides

all_assets = load_assets_from_modules([assets])

defs = Definitions(
    assets=all_assets,
    jobs=[squash_person_overrides],
)
