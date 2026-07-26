import time

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import ClickHouseUser, Workload, get_clickhouse_creds
from posthog.clickhouse.cluster import ON_CLUSTER_CLAUSE
from posthog.settings.data_stores import CLICKHOUSE_CLUSTER, CLICKHOUSE_DATABASE

DELETED_PERSON_IDS_DICTIONARY = "deleted_person_ids_dictionary"
_QUALIFIED_NAME = f"{CLICKHOUSE_DATABASE}.{DELETED_PERSON_IDS_DICTIONARY}"


def _wait_until_dictionary_loaded(timeout_seconds: int = 600) -> None:
    deadline = time.monotonic() + timeout_seconds
    while True:
        statuses = [
            status
            for (status,) in sync_execute(
                f"SELECT status FROM clusterAllReplicas('{CLICKHOUSE_CLUSTER}', system.dictionaries) "
                "WHERE database = %(database)s AND name = %(name)s",
                {"database": CLICKHOUSE_DATABASE, "name": DELETED_PERSON_IDS_DICTIONARY},
                workload=Workload.OFFLINE,
            )
        ]
        if statuses and all(status == "LOADED" for status in statuses):
            return
        if "FAILED" in statuses or time.monotonic() > deadline:
            raise Exception(f"{DELETED_PERSON_IDS_DICTIONARY} not loaded on all replicas: {statuses}")
        time.sleep(2.0)


def remove_deleted_person_data():
    """Hard-delete soft-deleted persons (rows with is_deleted > 0) from ClickHouse.

    The direct `DELETE FROM person WHERE id IN (SELECT id FROM person WHERE is_deleted > 0)`
    re-runs the whole-table subquery for every affected part, which does not scale as the
    table grows. Instead we load the ids to delete into a dictionary once and delete with
    dictHas(), so each part is scanned a single time.
    """
    dict_reader_user, dict_reader_password = get_clickhouse_creds(ClickHouseUser.DICT_READER)

    # `present` is an unused attribute; the dictionary is only probed with dictHas().
    sync_execute(
        f"""
        CREATE OR REPLACE DICTIONARY {_QUALIFIED_NAME} {ON_CLUSTER_CLAUSE()} (id UUID, present UInt8)
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

    try:
        sync_execute(
            f"SYSTEM RELOAD DICTIONARY {ON_CLUSTER_CLAUSE()} {_QUALIFIED_NAME}",
            workload=Workload.OFFLINE,
        )
        _wait_until_dictionary_loaded()

        # Synchronous so the dictionary is dropped only after the mutation is applied everywhere.
        sync_execute(
            f"DELETE FROM person WHERE dictHas('{_QUALIFIED_NAME}', id)",
            settings={"lightweight_deletes_sync": 2},
            workload=Workload.OFFLINE,
        )
    finally:
        sync_execute(
            f"DROP DICTIONARY IF EXISTS {_QUALIFIED_NAME} {ON_CLUSTER_CLAUSE()} SYNC",
            workload=Workload.OFFLINE,
        )
