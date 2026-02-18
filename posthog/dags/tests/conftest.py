# explicit fixture import is needed as autodiscovery doesn't work due to package layout
from posthog.conftest import django_db_setup

__all__ = ["django_db_setup"]

import os
import tempfile
from collections.abc import Iterator

import pytest
from posthog.test.base import reset_clickhouse_database
from unittest.mock import patch

import yaml

from posthog.clickhouse.cluster import ClickhouseCluster, get_cluster


def _patched_get_cluster_hosts(self, client, cluster, retry_policy=None):
    """
    Patch for local macOS Docker testing: use host_name instead of host_address.

    On macOS with Docker Desktop, system.clusters returns Docker-internal IPs
    (192.168.x.x) which aren't routable from the host. Using host_name returns
    "clickhouse" which resolves via /etc/hosts (set up by flox) to 127.0.0.1.
    """
    return client.execute(
        """
        SELECT host_name, port, shard_num, replica_num, getMacro('hostClusterType') as host_cluster_type, getMacro('hostClusterRole') as host_cluster_role
        FROM clusterAllReplicas(%(name)s, system.clusters)
        WHERE name = %(name)s and is_local
        ORDER BY shard_num, replica_num
        """,
        {"name": cluster},
    )


@pytest.fixture
def cluster(django_db_setup) -> Iterator[ClickhouseCluster]:
    """
    Cluster fixture with macOS Docker-compatible hostname resolution.
    Patches ClickhouseCluster to use host_name instead of host_address.
    """
    reset_clickhouse_database()
    try:
        with patch.object(
            ClickhouseCluster,
            "_ClickhouseCluster__get_cluster_hosts",
            _patched_get_cluster_hosts,
        ):
            yield get_cluster()
    finally:
        reset_clickhouse_database()


# ---------------------------------------------------------------------------
# PostgreSQL-backed DagsterInstance for tests
#
# Dagster's default ephemeral instance uses in-memory SQLite for event log and
# run storage. Under concurrent writes (common in Dagster job execution) this
# causes intermittent "database table is locked" errors. Replacing the storage
# backend with PostgreSQL eliminates these locking failures.
# ---------------------------------------------------------------------------

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
