from typing import Optional

from posthog.settings import CLICKHOUSE_ENABLE_STORAGE_POLICY, CLICKHOUSE_REPLICATION

STORAGE_POLICY = "SETTINGS storage_policy = 'hot_to_cold'" if CLICKHOUSE_ENABLE_STORAGE_POLICY else ""
TABLE_ENGINE = (
    "ReplicatedReplacingMergeTree('/clickhouse/tables/{{shard}}/posthog.{table}', '{{replica}}')"
    if CLICKHOUSE_REPLICATION
    else "MergeTree()"
)


def table_engine(table: str, engine_type: Optional[str] = None) -> str:
    if engine_type == "Replacing" and not CLICKHOUSE_REPLICATION:
        return "ReplacingMergeTree(created_at)"

    return TABLE_ENGINE.format(table=table)


DROP_TABLE_IF_EXISTS_SQL = """
DROP TABLE IF EXISTS {}
"""

GENERATE_UUID_SQL = """
SELECT generateUUIDv4()
"""
