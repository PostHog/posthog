import time
import uuid

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import ClickHouseUser, Workload, get_clickhouse_creds
from posthog.clickhouse.cluster import ON_CLUSTER_CLAUSE
from posthog.settings.data_stores import CLICKHOUSE_CLUSTER, CLICKHOUSE_DATABASE

# Prefix for the transient, per-run dictionary of person ids pending deletion.
DELETED_PERSON_IDS_DICTIONARY = "deleted_person_ids_dictionary"


def _wait_until_dictionary_loaded(name: str, timeout_seconds: int = 600) -> None:
    deadline = time.monotonic() + timeout_seconds
    while True:
        statuses = [
            status
            for (status,) in sync_execute(
                f"SELECT status FROM clusterAllReplicas('{CLICKHOUSE_CLUSTER}', system.dictionaries) "
                "WHERE database = %(database)s AND name = %(name)s",
                {"database": CLICKHOUSE_DATABASE, "name": name},
                workload=Workload.OFFLINE,
            )
        ]
        if statuses and all(status == "LOADED" for status in statuses):
            return
        if "FAILED" in statuses or time.monotonic() > deadline:
            raise Exception(f"{name} not loaded on all replicas: {statuses}")
        time.sleep(2.0)


def remove_deleted_person_data():
    """Hard-delete persons whose current (latest-version) state is deleted from ClickHouse.

    `person` is a ReplacingMergeTree keyed on (team_id, id); a person can be soft-deleted and
    later revived by a newer version, so whether to remove one is decided by the latest version
    -- argMax(is_deleted, version) > 0 -- not by any version having is_deleted > 0. The keys are
    loaded into a dictionary once and deleted with dictHas(), so each part is scanned a single
    time instead of re-running a whole-table subquery per affected part.
    """
    dict_reader_creds = get_clickhouse_creds(ClickHouseUser.DICT_READER)

    # Unique per invocation so overlapping runs never create, consume, or drop a shared
    # cluster-wide dictionary out from under each other.
    name = f"{DELETED_PERSON_IDS_DICTIONARY}_{uuid.uuid4().hex}"
    qualified = f"{CLICKHOUSE_DATABASE}.{name}"

    # Create inside the try so a partial cluster-wide create is still cleaned up by the finally.
    try:
        # Credentials are passed as query parameters so they are not interpolated into the
        # traced statement. `present` is an unused attribute; the dictionary is only probed
        # with dictHas().
        sync_execute(
            f"""
            CREATE OR REPLACE DICTIONARY {qualified} {ON_CLUSTER_CLAUSE()} (team_id Int64, id UUID, present UInt8)
            PRIMARY KEY team_id, id
            SOURCE(CLICKHOUSE(
                QUERY 'SELECT team_id, id, toUInt8(1) AS present FROM {CLICKHOUSE_DATABASE}.person WHERE (team_id, id) IN (SELECT team_id, id FROM {CLICKHOUSE_DATABASE}.person WHERE is_deleted > 0) GROUP BY team_id, id HAVING argMax(is_deleted, version) > 0'
                USER %(dict_reader_user)s PASSWORD %(dict_reader_password)s
            ))
            LAYOUT(COMPLEX_KEY_HASHED())
            LIFETIME(0)
            """,
            {"dict_reader_user": dict_reader_creds.user, "dict_reader_password": dict_reader_creds.password},
            workload=Workload.OFFLINE,
        )

        sync_execute(
            f"SYSTEM RELOAD DICTIONARY {ON_CLUSTER_CLAUSE()} {qualified}",
            workload=Workload.OFFLINE,
        )
        _wait_until_dictionary_loaded(name)

        # Synchronous so the dictionary is dropped only after the mutation is applied everywhere.
        sync_execute(
            f"DELETE FROM person WHERE dictHas('{qualified}', (team_id, id))",
            settings={"lightweight_deletes_sync": 2},
            workload=Workload.OFFLINE,
        )
    finally:
        sync_execute(
            f"DROP DICTIONARY IF EXISTS {qualified} {ON_CLUSTER_CLAUSE()} SYNC",
            workload=Workload.OFFLINE,
        )
