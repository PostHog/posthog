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
    """Hard-delete soft-deleted persons (rows with is_deleted > 0) from ClickHouse.

    The direct `DELETE FROM person WHERE id IN (SELECT id FROM person WHERE is_deleted > 0)`
    re-runs the whole-table subquery for every affected part, which does not scale as the
    table grows. Instead we load the ids to delete into a dictionary once and delete with
    dictHas(), so each part is scanned a single time.
    """
    dict_reader_user, dict_reader_password = get_clickhouse_creds(ClickHouseUser.DICT_READER)

    # Unique per invocation so overlapping runs never create, consume, or drop a shared
    # cluster-wide dictionary out from under each other.
    name = f"{DELETED_PERSON_IDS_DICTIONARY}_{uuid.uuid4().hex}"
    qualified = f"{CLICKHOUSE_DATABASE}.{name}"

    try:
        # `present` is an unused attribute; the dictionary is only probed with dictHas().
        sync_execute(
            f"""
            CREATE OR REPLACE DICTIONARY {qualified} {ON_CLUSTER_CLAUSE()} (id UUID, present UInt8)
            PRIMARY KEY id
            SOURCE(CLICKHOUSE(
                QUERY 'SELECT id, toUInt8(1) AS present FROM {CLICKHOUSE_DATABASE}.person WHERE is_deleted > 0'
                USER '{dict_reader_user}' PASSWORD '{dict_reader_password}'
            ))
            LAYOUT(COMPLEX_KEY_HASHED())
            LIFETIME(0)
            """,
            workload=Workload.OFFLINE,
        )

        sync_execute(
            f"SYSTEM RELOAD DICTIONARY {ON_CLUSTER_CLAUSE()} {qualified}",
            workload=Workload.OFFLINE,
        )
        _wait_until_dictionary_loaded(name)

        # Synchronous so the dictionary is dropped only after the mutation is applied everywhere.
        sync_execute(
            f"DELETE FROM person WHERE dictHas('{qualified}', id)",
            settings={"lightweight_deletes_sync": 2},
            workload=Workload.OFFLINE,
        )
    finally:
        sync_execute(
            f"DROP DICTIONARY IF EXISTS {qualified} {ON_CLUSTER_CLAUSE()} SYNC",
            workload=Workload.OFFLINE,
        )
