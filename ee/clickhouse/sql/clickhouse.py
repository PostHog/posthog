# Note for the vary: these engine definitions (and many table definitions) are not in sync with cloud!
from enum import Enum
from typing import Literal

from django.conf import settings


class ReplicationScheme(str, Enum):
    NOT_SHARDED = "NOT_SHARDED"
    SHARDED = "SHARDED"
    REPLICATED = "REPLICATED"


# Note: This does not list every table engine, just ones used in our codebase
class TableEngine(str, Enum):
    ReplacingMergeTree = "ReplacingMergeTree"
    CollapsingMergeTree = "CollapsingMergeTree"


STORAGE_POLICY = lambda: "SETTINGS storage_policy = 'hot_to_cold'" if settings.CLICKHOUSE_ENABLE_STORAGE_POLICY else ""

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


# Relevant documentation:
# - https://clickhouse.com/docs/en/engines/table-engines/mergetree-family/
# - https://clickhouse.com/docs/en/engines/table-engines/mergetree-family/replacingmergetree/
# - https://clickhouse.com/docs/en/engines/table-engines/mergetree-family/replication/
def table_engine(
    table: str,
    version_column: str,
    engine_type: TableEngine,
    replication_scheme: ReplicationScheme = ReplicationScheme.REPLICATED,
) -> str:
    if not settings.CLICKHOUSE_REPLICATION:
        replication_scheme = ReplicationScheme.NOT_SHARDED

    if replication_scheme == ReplicationScheme.NOT_SHARDED:
        return f"{engine_type}({version_column})"

    if replication_scheme == ReplicationScheme.SHARDED:
        shard_key, replica_key = "{shard}", "{replica}"
    else:
        shard_key, replica_key = "noshard", "{replica}-{shard}"

    return f"Replicated{engine_type}('/clickhouse/tables/{shard_key}/posthog.{table}', '{replica_key}', '{version_column}')"


def kafka_engine(
    topic: str,
    kafka_host=None,
    group="group1",
    serialization: Literal["JSONEachRow", "Protobuf"] = "JSONEachRow",
    proto_schema=None,
    skip_broken_messages=100,
):
    if kafka_host is None:
        kafka_host = settings.KAFKA_HOSTS_FOR_CLICKHOUSE
    if serialization == "Protobuf" and not settings.CLICKHOUSE_DISABLE_EXTERNAL_SCHEMAS:
        return KAFKA_PROTO_ENGINE.format(
            topic=topic,
            kafka_host=kafka_host,
            group=group,
            proto_schema=proto_schema,
            skip_broken_messages=skip_broken_messages,
        )
    else:
        return KAFKA_ENGINE.format(topic=topic, kafka_host=kafka_host, group=group, serialization="JSONEachRow")


def ttl_period(field: str = "created_at", weeks: int = 3):
    return "" if settings.TEST else f"TTL toDate({field}) + INTERVAL {weeks} WEEK"
