import pkgutil
import importlib

import pytest

import dagster

import posthog.dags.locations

LOCATION_MODULES = sorted(
    module.name
    for module in pkgutil.iter_modules(posthog.dags.locations.__path__)
    if module.name != "shared" and not module.ispkg
)


# Importing a location builds its Definitions lazily, so a job that selects an asset the location never
# registers only fails when the Dagster Cloud code server loads it. Resolve every job here instead.
@pytest.mark.parametrize("name", LOCATION_MODULES)
def test_location_definitions_resolve(name: str) -> None:
    module = importlib.import_module(f"posthog.dags.locations.{name}")

    dagster.Definitions.validate_loadable(module.defs)
