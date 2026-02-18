# ---------------------------------------------------------------------------
# PostgreSQL-backed DagsterInstance fixtures for tests
#
# Dagster's default ephemeral instance uses in-memory SQLite for event log and
# run storage. Under concurrent writes (common in Dagster job execution) this
# causes intermittent "database table is locked" errors. Replacing the storage
# backend with PostgreSQL eliminates these locking failures.
#
# This module is registered as a pytest plugin via ``pytest_plugins`` in any
# conftest.py that needs it (posthog/dags/tests and products/**/dags/tests).
# ---------------------------------------------------------------------------

import os
import tempfile

import pytest

import yaml

_DAGSTER_TEST_PG_URL = os.environ.get(
    "DAGSTER_TEST_POSTGRES_URL",
    "postgresql://posthog:posthog@localhost:5432/test_dagster",
)


@pytest.fixture(scope="session")
def _dagster_postgres_instance():
    """Session-scoped DagsterInstance backed by PostgreSQL.

    Uses the ``test_dagster`` database created by the Docker init script
    ``docker/postgres-init-scripts/create-dagster-test-db.sh``.
    """
    from dagster import DagsterInstance

    dagster_yaml = {
        "event_log_storage": {
            "module": "dagster_postgres.event_log",
            "class": "PostgresEventLogStorage",
            "config": {"postgres_url": _DAGSTER_TEST_PG_URL},
        },
        "run_storage": {
            "module": "dagster_postgres.run_storage",
            "class": "PostgresRunStorage",
            "config": {"postgres_url": _DAGSTER_TEST_PG_URL},
        },
        "schedule_storage": {
            "module": "dagster_postgres.schedule_storage",
            "class": "PostgresScheduleStorage",
            "config": {"postgres_url": _DAGSTER_TEST_PG_URL},
        },
    }

    with tempfile.TemporaryDirectory() as tmpdir:
        config_path = os.path.join(tmpdir, "dagster.yaml")
        with open(config_path, "w") as f:
            yaml.dump(dagster_yaml, f)

        instance = DagsterInstance.from_config(tmpdir)
        try:
            yield instance
        finally:
            instance.dispose()


@pytest.fixture(autouse=True)
def _use_postgres_dagster_instance(_dagster_postgres_instance):
    """Automatically replace Dagster's ephemeral instance with PostgreSQL.

    Monkeypatches ``ephemeral_instance_if_missing`` in the Dagster execution
    module so that every call to ``execute_in_process`` (which creates an
    ephemeral instance when ``instance=None``) uses the shared
    PostgreSQL-backed instance instead of in-memory SQLite.

    We patch at the ``ephemeral_instance_if_missing`` level rather than
    ``DagsterInstance.ephemeral`` because the latter is used as a context
    manager whose ``__exit__`` calls ``dispose()`` — which would destroy the
    shared session-scoped instance.
    """
    from contextlib import contextmanager

    import dagster._core.execution.execute_in_process as eip_module

    @contextmanager
    def _pg_ephemeral_instance_if_missing(instance):
        """Yield the PostgreSQL instance when no explicit instance is given."""
        if instance:
            yield instance
        else:
            yield _dagster_postgres_instance

    original = eip_module.ephemeral_instance_if_missing
    eip_module.ephemeral_instance_if_missing = _pg_ephemeral_instance_if_missing
    try:
        yield
    finally:
        eip_module.ephemeral_instance_if_missing = original
