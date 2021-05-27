from typing import Optional

from posthog.settings import CLICKHOUSE_ENABLE_STORAGE_POLICY, CLICKHOUSE_REPLICATION, KAFKA_HOSTS, TEST

STORAGE_POLICY = "SETTINGS storage_policy = 'hot_to_cold'" if CLICKHOUSE_ENABLE_STORAGE_POLICY else ""
REPLACING_TABLE_ENGINE = (
    "ReplicatedReplacingMergeTree('/clickhouse/tables/{{shard}}/posthog.{table}', '{{replica}}', {ver})"
    if CLICKHOUSE_REPLICATION
    else "ReplacingMergeTree({ver})"
)

MERGE_TABLE_ENGINE = (
    "ReplicatedReplacingMergeTree('/clickhouse/tables/{{shard}}/posthog.{table}', '{{replica}}')"
    if CLICKHOUSE_REPLICATION
    else "MergeTree()"
)

COLLAPSING_TABLE_ENGINE = (
    "ReplicatedCollapsingMergeTree('/clickhouse/tables/{{shard}}/posthog.{table}', '{{replica}}', {ver})"
    if CLICKHOUSE_REPLICATION
    else "CollapsingMergeTree({ver})"
)

KAFKA_ENGINE = "Kafka('{kafka_host}', '{topic}', '{group}', '{serialization}')"

KAFKA_PROTO_ENGINE = """
    Kafka () SETTINGS
    kafka_broker_list = '{kafka_host}',
    kafka_topic_list = '{topic}',
    kafka_group_name = '{group}',
    kafka_format = 'Protobuf',
    kafka_schema = '{proto_schema}',
    kafka_skip_broken_messages = {skip_broken_messages} 
    """

GENERATE_UUID_SQL = """
SELECT generateUUIDv4()
"""

KAFKA_COLUMNS = """
, _timestamp DateTime
, _offset UInt64
"""

COLLAPSING_MERGE_TREE = "collapsing_merge_tree"
REPLACING_MERGE_TREE = "replacing_merge_tree"


def table_engine(table: str, ver: Optional[str] = None, engine_type: Optional[str] = None) -> str:
    if engine_type == COLLAPSING_MERGE_TREE and ver:
        return COLLAPSING_TABLE_ENGINE.format(table=table, ver=ver)
    elif engine_type == REPLACING_MERGE_TREE and ver:
        return REPLACING_TABLE_ENGINE.format(table=table, ver=ver)
    else:
        return MERGE_TABLE_ENGINE.format(table=table)


def kafka_engine(
    topic: str,
    kafka_host=KAFKA_HOSTS,
    group="group1",
    serialization="JSONEachRow",
    proto_schema=None,
    skip_broken_messages=100,
):
    if serialization == "JSONEachRow":
        return KAFKA_ENGINE.format(topic=topic, kafka_host=kafka_host, group=group, serialization=serialization)
    elif serialization == "Protobuf":
        return KAFKA_PROTO_ENGINE.format(
            topic=topic,
            kafka_host=kafka_host,
            group=group,
            proto_schema=proto_schema,
            skip_broken_messages=skip_broken_messages,
        )


def ttl_period(field: str = "created_at", weeks: int = 3):
    return "" if TEST else f"TTL toDate({field}) + INTERVAL {weeks} WEEK"
