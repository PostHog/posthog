# Note for the vary: these engine definitions (and many table definitions) are not in sync with cloud!

from django.conf import settings

STORAGE_POLICY = lambda: "SETTINGS storage_policy = 'hot_to_cold'" if settings.CLICKHOUSE_ENABLE_STORAGE_POLICY else ""
REPLACING_TABLE_ENGINE = lambda: (
    "ReplicatedReplacingMergeTree('/clickhouse/tables/{shard_key}/posthog.{table}', '{replica_key}', {ver})"
    if settings.CLICKHOUSE_REPLICATION
    else "ReplacingMergeTree({ver})"
)

COLLAPSING_TABLE_ENGINE = lambda: (
    "ReplicatedCollapsingMergeTree('/clickhouse/tables/noshard/posthog.{table}', '{{replica}}-{{shard}}', {ver})"
    if settings.CLICKHOUSE_REPLICATION
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


# :TODO: Most table_engines calling this with sharded=True are out of sync with reality on cloud.
def table_engine(table: str, ver: str, engine_type: str, sharded=True) -> str:
    shard_key = "{shard}" if sharded else "noshard"
    replica_key = "{replica}" if sharded else "{replica}-{shard}"

    if engine_type == COLLAPSING_MERGE_TREE and ver:
        return COLLAPSING_TABLE_ENGINE().format(shard_key=shard_key, replica_key=replica_key, table=table, ver=ver)
    elif engine_type == REPLACING_MERGE_TREE and ver:
        return REPLACING_TABLE_ENGINE().format(shard_key=shard_key, replica_key=replica_key, table=table, ver=ver)
    else:
        raise ValueError(f"Unknown engine type {engine_type}")


def kafka_engine(
    topic: str,
    kafka_host=None,
    group="group1",
    serialization="JSONEachRow",
    proto_schema=None,
    skip_broken_messages=100,
):
    if kafka_host is None:
        kafka_host = settings.KAFKA_HOSTS_CLICKHOUSE
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
    return "" if settings.TEST else f"TTL toDate({field}) + INTERVAL {weeks} WEEK"
