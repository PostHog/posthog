from typing import Optional

from posthog.settings import CLICKHOUSE_ENABLE_STORAGE_POLICY, CLICKHOUSE_REPLICATION, KAFKA_HOSTS

STORAGE_POLICY = "SETTINGS storage_policy = 'hot_to_cold'" if CLICKHOUSE_ENABLE_STORAGE_POLICY else ""
TABLE_ENGINE = (
    "ReplicatedReplacingMergeTree('/clickhouse/tables/{{shard}}/posthog.{table}', '{{replica}}', {ver})"
    if CLICKHOUSE_REPLICATION
    else "ReplacingMergeTree({ver})"
)

TABLE_MERGE_ENGINE = (
    "ReplicatedReplacingMergeTree('/clickhouse/tables/{{shard}}/posthog.{table}', '{{replica}}')"
    if CLICKHOUSE_REPLICATION
    else "MergeTree()"
)

KAFKA_ENGINE = "Kafka('{kafka_host}', '{topic}', '{group}', '{serialization}')"

GENERATE_UUID_SQL = """
SELECT generateUUIDv4()
"""

KAFKA_COLUMNS = """
, _timestamp DateTime
, _offset UInt64
"""


def table_engine(table: str, ver: Optional[str] = None) -> str:
    if ver:
        return TABLE_ENGINE.format(table=table, ver=ver)
    else:
        return TABLE_MERGE_ENGINE.format(table=table)


def kafka_engine(topic: str, kafka_host=KAFKA_HOSTS, group="group1", serialization="JSONEachRow"):
    return KAFKA_ENGINE.format(topic=topic, kafka_host=kafka_host, group=group, serialization=serialization)
