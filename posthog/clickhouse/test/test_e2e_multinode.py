"""End-to-end infrastructure tests for multi-node ClickHouse dev stack.

Validates the 3-node dev stack (`clickhouse`, `clickhouse-coordinator`,
`clickhouse-logs`) against a single shared `keeper`:
- Per-node macros (shard, replica, hostClusterRole) via config.d overlays
- Sharded Distributed queries across the `posthog_migrations` cluster
- ON CLUSTER DDL propagation
- ReplicatedMergeTree with resolved macros in the znode path
- Shared Keeper with per-cluster path conventions (not per-cluster ensembles)

Prod runs independent Keeper ensembles per satellite cluster; dev collapses
to one Keeper for simplicity. If you need true Keeper-isolation tests, use
a dedicated compose overlay.

Start the stack:
    ./bin/ch-stack-up

Run the tests:
    ./bin/ch-test-multinode

Or directly:
    pytest posthog/clickhouse/test/test_e2e_multinode.py -v -m multinode
"""

import os
import uuid
import subprocess

import pytest

pytestmark = pytest.mark.multinode

# Per-run suffix for ReplicatedMergeTree ZK paths. The `test_db` fixture
# drops tables between runs, but if a run is interrupted (SIGINT, OOM,
# docker restart) stale znodes under `/clickhouse/tables/<shard>/...`
# outlive the DB and cause the next `CREATE TABLE` to fail with
# "replica path already exists". Embedding a per-run UUID keeps ZK paths
# unique even when cleanup didn't run.
TEST_RUN_SUFFIX = uuid.uuid4().hex[:8]
ZK_PATH_PREFIX = f"/clickhouse/tables/{{shard}}/test_{TEST_RUN_SUFFIX}"


def _try_connect(host_env, host_default, port_env, port_default):
    """Attempt CH connection, return client or None."""
    from clickhouse_driver import Client

    host = os.environ.get(host_env, host_default)
    port = int(os.environ.get(port_env, str(port_default)))
    try:
        c = Client(host=host, port=port, connect_timeout=5)
        c.execute("SELECT 1")
        return c
    except Exception:
        return None


@pytest.fixture(scope="module")
def multinode_stack_available():
    """Skip the module only when the dev-coordinator stack isn't running.

    Previously we gated on `posthog_migrations` shard count, but that is
    the exact condition these tests exist to verify — if the cluster
    config regressed to a single shard, skipping the suite would hide
    the regression. Detect "stack absent" by asking compose whether the
    clickhouse container exists instead.
    """
    try:
        result = subprocess.run(
            [
                "docker",
                "compose",
                "-p",
                "posthog-multinode",
                "-f",
                "docker-compose.dev-coordinator.yml",
                "ps",
                "-q",
                "clickhouse",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pytest.skip("docker compose unavailable; cannot detect multinode stack")
    if result.returncode != 0 or not result.stdout.strip():
        pytest.skip("Multi-node dev stack not running. Start with `bin/ch-stack-up`.")
    return True


@pytest.fixture(scope="module")
def ch_main(multinode_stack_available):
    """Main cluster node (keeper-main, shard 01, data role)."""
    client = _try_connect("CLICKHOUSE_HOST", "localhost", "CLICKHOUSE_PORT", 9000)
    if client is None:
        pytest.skip("clickhouse node not reachable on localhost:9000")
    return client


@pytest.fixture(scope="module")
def ch_coordinator():
    """Coordinator node (keeper-main, shard 02, coordinator role)."""
    client = _try_connect("CLICKHOUSE_COORD_HOST", "localhost", "CLICKHOUSE_COORD_PORT", 9001)
    if client is None:
        pytest.skip("clickhouse-coordinator not reachable on localhost:9001")
    return client


@pytest.fixture(scope="module")
def ch_logs():
    """Logs node (shares `keeper` with main/coordinator, shard 01, logs role)."""
    client = _try_connect("CLICKHOUSE_LOGS_HOST", "localhost", "CLICKHOUSE_LOGS_PORT", 9002)
    if client is None:
        pytest.skip("clickhouse-logs not reachable on localhost:9002")
    return client


@pytest.fixture(scope="module")
def test_db(ch_main):
    """Create and drop a test database for the module."""
    db = "e2e_multinode_test"
    # Create on all cluster nodes so coordinator queries against this DB also succeed
    ch_main.execute(f"CREATE DATABASE IF NOT EXISTS {db} ON CLUSTER posthog_migrations")
    yield db
    # Cleanup: drop all tables on cluster, then the database on cluster
    for (name,) in ch_main.execute(f"SELECT name FROM system.tables WHERE database = '{db}'"):
        ch_main.execute(f"DROP TABLE IF EXISTS {db}.{name} ON CLUSTER posthog_migrations SYNC")
    ch_main.execute(f"DROP DATABASE IF EXISTS {db} ON CLUSTER posthog_migrations SYNC")


# ── Cluster Topology Tests ──


class TestClusterTopology:
    """Verify cluster definitions match expected dev topology."""

    def test_posthog_cluster_exists(self, ch_main):
        rows = ch_main.execute("SELECT count() FROM system.clusters WHERE cluster = 'posthog'")
        assert rows[0][0] > 0, "posthog cluster not defined"

    def test_posthog_migrations_has_two_shards(self, ch_main):
        rows = ch_main.execute("SELECT uniq(shard_num) FROM system.clusters WHERE cluster = 'posthog_migrations'")
        assert rows[0][0] == 2, f"Expected 2 shards, got {rows[0][0]}"

    def test_main_node_macros(self, ch_main):
        macros = dict(ch_main.execute("SELECT macro, substitution FROM system.macros"))
        assert macros.get("shard") == "01"
        assert macros.get("replica") == "ch1"
        assert macros.get("hostClusterRole") == "data"

    def test_coordinator_node_macros(self, ch_coordinator):
        macros = dict(ch_coordinator.execute("SELECT macro, substitution FROM system.macros"))
        assert macros.get("shard") == "02"
        assert macros.get("replica") == "coord"
        assert macros.get("hostClusterRole") == "coordinator"

    def test_logs_node_macros(self, ch_logs):
        macros = dict(ch_logs.execute("SELECT macro, substitution FROM system.macros"))
        assert macros.get("shard") == "01"
        assert macros.get("replica") == "ch1"
        assert macros.get("hostClusterRole") == "logs"


# ── Keeper Connectivity Tests ──


class TestKeeperConnectivity:
    """All three nodes share a single Keeper in the dev stack.

    Production runs independent Keeper ensembles per satellite cluster
    (see `PostHog ClickHouse Physical Cluster Layout` in the vault). Dev
    collapses to one Keeper for simplicity — per-cluster isolation is
    achieved via znode path conventions in CREATE TABLE statements
    (`/clickhouse/{cluster}/tables/...`), not separate ensembles.
    """

    def test_main_node_connects_to_keeper(self, ch_main):
        rows = ch_main.execute("SELECT host FROM system.zookeeper_connection")
        assert len(rows) > 0, "No zookeeper connection on main node"
        assert rows[0][0] == "keeper", f"Main connected to '{rows[0][0]}', expected 'keeper'"

    def test_coordinator_connects_to_keeper(self, ch_coordinator):
        rows = ch_coordinator.execute("SELECT host FROM system.zookeeper_connection")
        assert len(rows) > 0
        assert rows[0][0] == "keeper", f"Coordinator connected to '{rows[0][0]}', expected 'keeper'"

    def test_logs_node_connects_to_keeper(self, ch_logs):
        rows = ch_logs.execute("SELECT host FROM system.zookeeper_connection")
        assert len(rows) > 0, "No zookeeper connection on logs node"
        assert rows[0][0] == "keeper", f"Logs connected to '{rows[0][0]}', expected 'keeper'"

    def test_znode_path_visibility(self, ch_main, ch_logs, test_db):
        """A ReplicatedMergeTree path created on main IS visible from logs —
        same Keeper, same namespace. Per-cluster isolation is achieved in
        table DDL via the `/clickhouse/{cluster}/...` path convention, not
        at the Keeper level."""
        tbl = f"{test_db}.isolation_probe"
        ch_main.execute(
            f"CREATE TABLE {tbl} (id UInt64) "
            f"ENGINE = ReplicatedMergeTree('{ZK_PATH_PREFIX}/{tbl}', '{{replica}}') "
            f"ORDER BY id"
        )
        try:
            # Both nodes query the same keeper, so both see the znode.
            zk_path_resolved = f"/clickhouse/tables/01/test_{TEST_RUN_SUFFIX}/{tbl}"
            main_zk = ch_main.execute(f"SELECT count() FROM system.zookeeper WHERE path = '{zk_path_resolved}'")
            assert main_zk[0][0] > 0, "znode not visible on main node"

            logs_zk = ch_logs.execute(f"SELECT count() FROM system.zookeeper WHERE path = '{zk_path_resolved}'")
            assert logs_zk[0][0] > 0, "znode not visible on logs node — keeper sharing broken"
        finally:
            ch_main.execute(f"DROP TABLE IF EXISTS {tbl} SYNC")


# ── Sharded Distributed Tests ──


class TestShardedDistributed:
    """Verify cross-shard queries work via posthog_migrations cluster."""

    def test_on_cluster_ddl_propagates(self, ch_main, ch_coordinator, test_db):
        """ON CLUSTER DDL creates table on both shards."""
        tbl = f"{test_db}.ddl_prop"
        ch_main.execute(f"CREATE TABLE {tbl} ON CLUSTER posthog_migrations (id UInt64) ENGINE = MergeTree ORDER BY id")
        try:
            main_exists = ch_main.execute(
                f"SELECT count() FROM system.tables WHERE database = '{test_db}' AND name = 'ddl_prop'"
            )
            coord_exists = ch_coordinator.execute(
                f"SELECT count() FROM system.tables WHERE database = '{test_db}' AND name = 'ddl_prop'"
            )
            assert main_exists[0][0] == 1, "Table not created on main"
            assert coord_exists[0][0] == 1, "Table not created on coordinator"
        finally:
            ch_main.execute(f"DROP TABLE IF EXISTS {tbl} ON CLUSTER posthog_migrations SYNC")

    def test_distributed_routes_to_both_shards(self, ch_main, ch_coordinator, test_db):
        """Distributed query hits both shards."""
        local = f"{test_db}.shard_local"
        dist = f"{test_db}.shard_dist"

        ch_main.execute(
            f"CREATE TABLE {local} ON CLUSTER posthog_migrations "
            f"(id UInt64, team_id Int64) "
            f"ENGINE = ReplicatedMergeTree("
            f"'{ZK_PATH_PREFIX}/{local}', '{{replica}}') "
            f"ORDER BY (team_id, id)"
        )
        try:
            # Insert directly on each shard's local table
            ch_main.execute(f"INSERT INTO {local} VALUES (1, 1)")
            ch_coordinator.execute(f"INSERT INTO {local} VALUES (2, 2)")

            # Create Distributed table
            ch_main.execute(
                f"CREATE TABLE {dist} ON CLUSTER posthog_migrations "
                f"AS {local} "
                f"ENGINE = Distributed('posthog_migrations', '{test_db}', "
                f"'shard_local', cityHash64(id))"
            )

            # Query via Distributed should see both rows
            count = ch_main.execute(f"SELECT count() FROM {dist}")
            assert count[0][0] == 2, f"Expected 2 rows, got {count[0][0]}"
        finally:
            ch_main.execute(f"DROP TABLE IF EXISTS {dist} ON CLUSTER posthog_migrations SYNC")
            ch_main.execute(f"DROP TABLE IF EXISTS {local} ON CLUSTER posthog_migrations SYNC")

    def test_alter_on_cluster_propagates(self, ch_main, ch_coordinator, test_db):
        """ALTER ADD COLUMN via ON CLUSTER reaches both shards."""
        tbl = f"{test_db}.alter_prop"
        ch_main.execute(
            f"CREATE TABLE {tbl} ON CLUSTER posthog_migrations "
            f"(id UInt64) "
            f"ENGINE = ReplicatedMergeTree("
            f"'{ZK_PATH_PREFIX}/{tbl}', '{{replica}}') "
            f"ORDER BY id"
        )
        try:
            ch_main.execute(f"ALTER TABLE {tbl} ON CLUSTER posthog_migrations ADD COLUMN IF NOT EXISTS c1 String")
            main_cols = {
                r[0]
                for r in ch_main.execute(
                    f"SELECT name FROM system.columns WHERE database = '{test_db}' AND table = 'alter_prop'"
                )
            }
            coord_cols = {
                r[0]
                for r in ch_coordinator.execute(
                    f"SELECT name FROM system.columns WHERE database = '{test_db}' AND table = 'alter_prop'"
                )
            }
            assert "c1" in main_cols, "Column not added on main"
            assert "c1" in coord_cols, "Column not added on coordinator"
        finally:
            ch_main.execute(f"DROP TABLE IF EXISTS {tbl} ON CLUSTER posthog_migrations SYNC")


# ── Drift Detection Tests ──


class TestDriftDetection:
    """Verify schema differences between nodes can be detected."""

    def test_detect_column_drift(self, ch_main, ch_coordinator, test_db):
        """Schema diff between nodes is detectable via system.columns."""
        tbl_name = "drift_probe"
        # Create on main only (not ON CLUSTER) so coordinator gets nothing
        ch_main.execute(f"CREATE TABLE {test_db}.{tbl_name} (id UInt64, name String) ENGINE = MergeTree ORDER BY id")
        # Create on coordinator with extra column
        ch_coordinator.execute(
            f"CREATE TABLE {test_db}.{tbl_name} (id UInt64, name String, extra String) ENGINE = MergeTree ORDER BY id"
        )
        try:
            main_cols = {
                r[0]
                for r in ch_main.execute(
                    f"SELECT name FROM system.columns WHERE database = '{test_db}' AND table = '{tbl_name}'"
                )
            }
            coord_cols = {
                r[0]
                for r in ch_coordinator.execute(
                    f"SELECT name FROM system.columns WHERE database = '{test_db}' AND table = '{tbl_name}'"
                )
            }
            drift = coord_cols - main_cols
            assert drift == {"extra"}, f"Expected drift {{'extra'}}, got {drift}"
        finally:
            ch_main.execute(f"DROP TABLE IF EXISTS {test_db}.{tbl_name} SYNC")
            ch_coordinator.execute(f"DROP TABLE IF EXISTS {test_db}.{tbl_name} SYNC")


# ── ReplicatedMergeTree ZK Path Tests ──


class TestReplicatedMergeTree:
    """Verify ReplicatedMergeTree uses correct ZK paths with macros."""

    def test_zk_path_uses_shard_macro(self, ch_main, test_db):
        tbl = f"{test_db}.rmt_path_test"
        ch_main.execute(
            f"CREATE TABLE {tbl} (id UInt64) "
            f"ENGINE = ReplicatedMergeTree("
            f"'{ZK_PATH_PREFIX}/{tbl}', '{{replica}}') "
            f"ORDER BY id"
        )
        try:
            # system.replicas.zookeeper_path has the *resolved* shard macro,
            # whereas system.tables.engine_full shows the original DDL text
            # with `{shard}` still a literal.
            rows = ch_main.execute(
                f"SELECT zookeeper_path, replica_name FROM system.replicas "
                f"WHERE database = '{test_db}' AND table = 'rmt_path_test'"
            )
            assert rows, "replica row not found in system.replicas"
            zookeeper_path, replica_name = rows[0]
            assert "/01/" in zookeeper_path, f"shard macro not resolved in ZK path: {zookeeper_path}"
            assert replica_name == "ch1", f"replica macro not resolved: {replica_name}"
        finally:
            ch_main.execute(f"DROP TABLE IF EXISTS {tbl} SYNC")

    def test_replicated_table_on_cluster(self, ch_main, ch_coordinator, test_db):
        """ReplicatedMergeTree ON CLUSTER gets different shard in ZK path per node."""
        tbl = f"{test_db}.rmt_cluster"
        ch_main.execute(
            f"CREATE TABLE {tbl} ON CLUSTER posthog_migrations "
            f"(id UInt64) "
            f"ENGINE = ReplicatedMergeTree("
            f"'{ZK_PATH_PREFIX}/{tbl}', '{{replica}}') "
            f"ORDER BY id"
        )
        try:
            # Use system.replicas.zookeeper_path — it has the resolved {shard} macro.
            # system.tables.engine_full keeps the literal `{shard}` DDL text and won't
            # show the per-node shard number.
            main_zk_path = ch_main.execute(
                f"SELECT zookeeper_path FROM system.replicas WHERE database = '{test_db}' AND table = 'rmt_cluster'"
            )[0][0]
            coord_zk_path = ch_coordinator.execute(
                f"SELECT zookeeper_path FROM system.replicas WHERE database = '{test_db}' AND table = 'rmt_cluster'"
            )[0][0]
            # Main is shard 01, coordinator is shard 02
            assert "/01/" in main_zk_path, f"main shard macro not resolved: {main_zk_path}"
            assert "/02/" in coord_zk_path, f"coordinator shard macro not resolved: {coord_zk_path}"
        finally:
            ch_main.execute(f"DROP TABLE IF EXISTS {tbl} ON CLUSTER posthog_migrations SYNC")
