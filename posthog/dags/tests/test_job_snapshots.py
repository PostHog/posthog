import importlib

import pytest

from posthog.dags.tests.test_loggers import LOCATION_MODULES


# Dagster records a dict's key type without the types nested in it. A dict keyed by a tuple of a
# custom type leaves that type out of the job snapshot, and the job's Overview tab fails to load.
@pytest.mark.parametrize("module_name", LOCATION_MODULES)
def test_every_job_snapshot_records_the_types_its_ops_name(module_name: str) -> None:
    module = importlib.import_module(f"posthog.dags.locations.{module_name}")

    missing: dict[str, set[str]] = {}
    for job in module.defs.resolve_all_job_defs():
        types = job.get_job_snapshot().dagster_type_namespace_snapshot.all_dagster_type_snaps_by_key
        for type_snap in types.values():
            for param_key in type_snap.type_param_keys:
                if param_key not in types:
                    missing.setdefault(job.name, set()).add(param_key)

    assert missing == {}
