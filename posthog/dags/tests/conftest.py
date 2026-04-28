from collections.abc import Iterator

import pytest
from posthog.test.base import reset_clickhouse_database
from unittest.mock import patch

from posthog.clickhouse.cluster import ClickhouseCluster, get_cluster
from posthog.conftest import reset_clickhouse_tables

# Import the shared Dagster PostgreSQL fixtures so they apply to all tests
# in this directory. Direct import (rather than pytest_plugins) is required
# because pytest disallows pytest_plugins in non-top-level conftest files.
from posthog.dags.tests.dagster_pg_fixtures import (  # noqa: F401
    _dagster_postgres_instance,
    _use_postgres_dagster_instance,
)

TRUNCATE_CLICKHOUSE_RESET_MARKER = "truncate_clickhouse_reset"


@pytest.fixture(scope="module", autouse=True)
def _reset_clickhouse_schema_for_truncate_cluster_tests(request: pytest.FixtureRequest) -> Iterator[None]:
    module_items = getattr(request.node, "items", [])
    if not any(
        "cluster" in item.fixturenames and item.get_closest_marker(TRUNCATE_CLICKHOUSE_RESET_MARKER)
        for item in module_items
    ):
        yield
        return

    request.getfixturevalue("django_db_setup")
    reset_clickhouse_database()
    try:
        yield
    finally:
        reset_clickhouse_database()


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
def cluster(request: pytest.FixtureRequest, django_db_setup) -> Iterator[ClickhouseCluster]:
    """
    Cluster fixture with macOS Docker-compatible hostname resolution.
    Patches ClickhouseCluster to use host_name instead of host_address.
    """
    reset_clickhouse = (
        reset_clickhouse_tables
        if request.node.get_closest_marker(TRUNCATE_CLICKHOUSE_RESET_MARKER)
        else reset_clickhouse_database
    )
    reset_clickhouse()
    try:
        with patch.object(
            ClickhouseCluster,
            "_ClickhouseCluster__get_cluster_hosts",
            _patched_get_cluster_hosts,
        ):
            yield get_cluster()
    finally:
        reset_clickhouse()
