import time
import uuid

import pytest

from django.conf import settings

from clickhouse_driver import Client as SyncClient

from posthog.clickhouse.test.test_replication_utils import (
    REPLICA_SECONDARY_HOST,
    REPLICA_SECONDARY_NATIVE_PORT,
    make_client,
    start_replication,
    stop_replication,
)


def _ensure_database(host: str, port: int, database: str) -> None:
    client = make_client(host, port, "system")
    client.execute(f"CREATE DATABASE IF NOT EXISTS {database}")
    client.disconnect()


def _create_replicated_cohortpeople(primary: SyncClient, replica: SyncClient, table_name: str, zk_path: str) -> None:
    for client, replica_name in [(primary, "ch1"), (replica, "ch2")]:
        client.execute(f"""
            CREATE TABLE IF NOT EXISTS {table_name}
            (
                person_id UUID,
                cohort_id Int64,
                team_id Int64,
                sign Int8,
                version UInt64
            )
            ENGINE = ReplicatedCollapsingMergeTree('{zk_path}', '{replica_name}', sign)
            ORDER BY (team_id, cohort_id, person_id, version)
        """)


def _drop_table(client: SyncClient, table_name: str) -> None:
    client.execute(f"DROP TABLE IF EXISTS {table_name} SYNC")


def _count_rows(client: SyncClient, table_name: str, cohort_id: int, version: int) -> int:
    result = client.execute(
        f"SELECT count() FROM {table_name} WHERE cohort_id = %(cohort_id)s AND version = %(version)s AND sign = 1",
        {"cohort_id": cohort_id, "version": version},
    )
    return result[0][0]


def _wait_for_rows(
    client: SyncClient, table_name: str, cohort_id: int, version: int, expected: int, timeout: float = 15.0
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _count_rows(client, table_name, cohort_id, version) == expected:
            return
        time.sleep(0.3)
    actual = _count_rows(client, table_name, cohort_id, version)
    raise AssertionError(f"Expected {expected} rows for cohort_id={cohort_id} version={version}, got {actual}")


pytestmark = pytest.mark.ch_replication

CH_PRIMARY_PORT = 9000


@pytest.fixture()
def replication_env():
    db = settings.CLICKHOUSE_DATABASE
    test_id = uuid.uuid4().hex[:8]
    table_name = f"test_cohortpeople_{test_id}"
    zk_path = f"/clickhouse/tables/replication_test/{test_id}/posthog.cohortpeople"

    _ensure_database(settings.CLICKHOUSE_HOST, CH_PRIMARY_PORT, db)
    _ensure_database(REPLICA_SECONDARY_HOST, REPLICA_SECONDARY_NATIVE_PORT, db)

    primary = make_client(settings.CLICKHOUSE_HOST, CH_PRIMARY_PORT, db)
    replica = make_client(REPLICA_SECONDARY_HOST, REPLICA_SECONDARY_NATIVE_PORT, db)

    _create_replicated_cohortpeople(primary, replica, table_name, zk_path)

    tables_to_drop = [table_name]

    yield primary, replica, table_name, tables_to_drop

    start_replication(replica, table_name)
    for t in tables_to_drop:
        _drop_table(primary, t)
        _drop_table(replica, t)
    primary.disconnect()
    replica.disconnect()


TEAM_ID = 1
COHORT_ID = 99


@pytest.mark.timeout(60)
class TestCohortpeopleReplicationLag:
    def test_cohortpeople_replication_lag_causes_zero_count(self, replication_env):
        primary, replica, table, _ = replication_env
        person_id = str(uuid.uuid4())

        primary.execute(
            f"INSERT INTO {table} (person_id, cohort_id, team_id, sign, version) VALUES",
            [(person_id, COHORT_ID, TEAM_ID, 1, 1)],
        )
        _wait_for_rows(replica, table, COHORT_ID, version=1, expected=1)

        stop_replication(replica, table)

        primary.execute(
            f"INSERT INTO {table} (person_id, cohort_id, team_id, sign, version) VALUES",
            [(person_id, COHORT_ID, TEAM_ID, 1, 2)],
        )

        # Primary has v2, replica does NOT — this is the replication lag bug (#47618)
        assert _count_rows(primary, table, COHORT_ID, version=2) == 1
        assert _count_rows(replica, table, COHORT_ID, version=2) == 0

        start_replication(replica, table)
        _wait_for_rows(replica, table, COHORT_ID, version=2, expected=1)

    def test_cohortpeople_sync_replica_prevents_stale_read(self, replication_env):
        primary, replica, table, _ = replication_env
        person_id = str(uuid.uuid4())

        primary.execute(
            f"INSERT INTO {table} (person_id, cohort_id, team_id, sign, version) VALUES",
            [(person_id, COHORT_ID, TEAM_ID, 1, 1)],
        )
        _wait_for_rows(replica, table, COHORT_ID, version=1, expected=1)

        stop_replication(replica, table)

        primary.execute(
            f"INSERT INTO {table} (person_id, cohort_id, team_id, sign, version) VALUES",
            [(person_id, COHORT_ID, TEAM_ID, 1, 2)],
        )

        assert _count_rows(primary, table, COHORT_ID, version=2) == 1
        assert _count_rows(replica, table, COHORT_ID, version=2) == 0

        # START FETCHES then SYNC REPLICA deterministically waits for pending parts
        start_replication(replica, table)
        replica.execute(
            f"SYSTEM SYNC REPLICA {table}",
            settings={"receive_timeout": 30},
        )

        assert _count_rows(replica, table, COHORT_ID, version=2) == 1

    def test_in_order_load_balancing_avoids_stale_read(self, replication_env):
        primary, replica, table, tables_to_drop = replication_env
        db = settings.CLICKHOUSE_DATABASE
        cluster = settings.CLICKHOUSE_CLUSTER
        person_id = str(uuid.uuid4())

        dist_table = f"{table}_dist"
        primary.execute(f"""
            CREATE TABLE IF NOT EXISTS {dist_table} AS {table}
            ENGINE = Distributed('{cluster}', '{db}', '{table}')
        """)
        tables_to_drop.append(dist_table)

        primary.execute(
            f"INSERT INTO {table} (person_id, cohort_id, team_id, sign, version) VALUES",
            [(person_id, COHORT_ID, TEAM_ID, 1, 1)],
        )
        _wait_for_rows(replica, table, COHORT_ID, version=1, expected=1)

        stop_replication(replica, table)
        primary.execute(
            f"INSERT INTO {table} (person_id, cohort_id, team_id, sign, version) VALUES",
            [(person_id, COHORT_ID, TEAM_ID, 1, 2)],
        )

        assert _count_rows(primary, table, COHORT_ID, version=2) == 1
        assert _count_rows(replica, table, COHORT_ID, version=2) == 0

        # in_order prefers the first replica in cluster config (ch1 = primary)
        result = primary.execute(
            f"""SELECT count() FROM {dist_table}
                WHERE cohort_id = %(cohort_id)s AND version = %(version)s AND sign = 1""",
            {"cohort_id": COHORT_ID, "version": 2},
            settings={"load_balancing": "in_order"},
        )
        assert result[0][0] == 1

        start_replication(replica, table)
        _wait_for_rows(replica, table, COHORT_ID, version=2, expected=1)

    def test_sequential_consistency_does_not_prevent_stale_read(self, replication_env):
        primary, replica, table, _ = replication_env
        person_id = str(uuid.uuid4())

        primary.execute(
            f"INSERT INTO {table} (person_id, cohort_id, team_id, sign, version) VALUES",
            [(person_id, COHORT_ID, TEAM_ID, 1, 1)],
        )
        _wait_for_rows(replica, table, COHORT_ID, version=1, expected=1)

        stop_replication(replica, table)
        primary.execute(
            f"INSERT INTO {table} (person_id, cohort_id, team_id, sign, version) VALUES",
            [(person_id, COHORT_ID, TEAM_ID, 1, 2)],
        )

        assert _count_rows(primary, table, COHORT_ID, version=2) == 1
        assert _count_rows(replica, table, COHORT_ID, version=2) == 0

        # Query with select_sequential_consistency while fetches are still stopped.
        # The setting checks ZK log pointers but does NOT block until data parts
        # are actually fetched — still returns 0 despite the consistency guarantee.
        result = replica.execute(
            f"""SELECT count() FROM {table}
                WHERE cohort_id = %(cohort_id)s AND version = %(version)s AND sign = 1""",
            {"cohort_id": COHORT_ID, "version": 2},
            settings={"select_sequential_consistency": 1, "receive_timeout": 10},
        )
        assert result[0][0] == 0

        # Contrast: SYNC REPLICA actually waits for data parts
        start_replication(replica, table)
        replica.execute(
            f"SYSTEM SYNC REPLICA {table}",
            settings={"receive_timeout": 30},
        )
        assert _count_rows(replica, table, COHORT_ID, version=2) == 1
