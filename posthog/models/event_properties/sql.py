from posthog.clickhouse.kafka_engine import KAFKA_COLUMNS_WITH_PARTITION, kafka_engine
from posthog.clickhouse.table_engines import Distributed, ReplacingMergeTree, ReplicationScheme
from posthog.kafka_client.topics import KAFKA_CLICKHOUSE_EVENT_PROPERTIES
from posthog.settings import CLICKHOUSE_CLUSTER

EVENT_PROPERTIES_TABLE = "event_properties"
EVENT_PROPERTIES_SHARDED_TABLE = "sharded_event_properties"
EVENT_PROPERTIES_WRITABLE_TABLE = "writable_event_properties"
EVENT_PROPERTIES_KAFKA_TABLE = "kafka_event_properties"
EVENT_PROPERTIES_MV = "event_properties_mv"

EVENT_PROPERTIES_COLUMNS = """
    team_id Int64,
    timestamp DateTime64(6, 'UTC'),
    event String,
    distinct_id String,
    uuid UUID,
    key String,
    value_string Nullable(String),
    value_numeric Nullable(Float64),
    value_bool Nullable(UInt8),
    value_datetime Nullable(DateTime64(6, 'UTC'))
"""

EVENT_PROPERTIES_INDEXES = """
    INDEX bloom_filter_key key TYPE bloom_filter GRANULARITY 1,
    INDEX bloom_filter_value_string value_string TYPE bloom_filter GRANULARITY 1,
    INDEX bloom_filter_value_numeric value_numeric TYPE bloom_filter GRANULARITY 1,
    INDEX bloom_filter_value_bool value_bool TYPE bloom_filter GRANULARITY 1,
    INDEX bloom_filter_value_datetime value_datetime TYPE bloom_filter GRANULARITY 1
"""


def DROP_EVENT_PROPERTIES_SHARDED_TABLE_SQL():
    return f"DROP TABLE IF EXISTS {EVENT_PROPERTIES_SHARDED_TABLE} SYNC"


def DROP_EVENT_PROPERTIES_WRITABLE_TABLE_SQL():
    return f"DROP TABLE IF EXISTS {EVENT_PROPERTIES_WRITABLE_TABLE}"


def DROP_EVENT_PROPERTIES_DISTRIBUTED_TABLE_SQL():
    return f"DROP TABLE IF EXISTS {EVENT_PROPERTIES_TABLE}"


def DROP_EVENT_PROPERTIES_MV_SQL():
    return f"DROP TABLE IF EXISTS {EVENT_PROPERTIES_MV}"


def DROP_EVENT_PROPERTIES_KAFKA_TABLE_SQL():
    return f"DROP TABLE IF EXISTS {EVENT_PROPERTIES_KAFKA_TABLE}"


def EVENT_PROPERTIES_SHARDED_TABLE_SQL():
    return """
CREATE TABLE IF NOT EXISTS {table_name}
(
    {columns}
    {kafka_columns}
    {indexes}
)
ENGINE = {engine}
PARTITION BY toYYYYMM(timestamp)
ORDER BY (team_id, toDate(timestamp), event, cityHash64(distinct_id), cityHash64(uuid), key)
""".format(
        table_name=EVENT_PROPERTIES_SHARDED_TABLE,
        columns=EVENT_PROPERTIES_COLUMNS,
        kafka_columns=KAFKA_COLUMNS_WITH_PARTITION,
        indexes=", " + EVENT_PROPERTIES_INDEXES,
        engine=ReplacingMergeTree(
            EVENT_PROPERTIES_SHARDED_TABLE,
            replication_scheme=ReplicationScheme.SHARDED,
            ver="_timestamp",
        ),
    )


def EVENT_PROPERTIES_DISTRIBUTED_TABLE_SQL(table_name: str = EVENT_PROPERTIES_TABLE):
    return """
CREATE TABLE IF NOT EXISTS {table_name}
(
    {columns}
    {kafka_columns}
)
ENGINE = {engine}
""".format(
        table_name=table_name,
        columns=EVENT_PROPERTIES_COLUMNS,
        kafka_columns=KAFKA_COLUMNS_WITH_PARTITION,
        engine=Distributed(
            data_table=EVENT_PROPERTIES_SHARDED_TABLE,
            cluster=CLICKHOUSE_CLUSTER,
            sharding_key="sipHash64(distinct_id)",
        ),
    )


def EVENT_PROPERTIES_WRITABLE_TABLE_SQL():
    return EVENT_PROPERTIES_DISTRIBUTED_TABLE_SQL(table_name=EVENT_PROPERTIES_WRITABLE_TABLE)


def KAFKA_EVENT_PROPERTIES_TABLE_SQL():
    return """
CREATE TABLE IF NOT EXISTS {table_name}
(
    {columns}
)
ENGINE = {engine}
SETTINGS kafka_max_block_size = 1000000, kafka_poll_max_batch_size = 100000, kafka_poll_timeout_ms = 1000, kafka_flush_interval_ms = 7500, kafka_skip_broken_messages = 100, kafka_num_consumers = 1
""".format(
        table_name=EVENT_PROPERTIES_KAFKA_TABLE,
        columns=EVENT_PROPERTIES_COLUMNS,
        engine=kafka_engine(topic=KAFKA_CLICKHOUSE_EVENT_PROPERTIES, group="clickhouse_event_properties"),
    )


def EVENT_PROPERTIES_MV_SQL():
    return """
CREATE MATERIALIZED VIEW IF NOT EXISTS {mv_name} TO {writable_table_name}
AS SELECT
    team_id,
    timestamp,
    event,
    distinct_id,
    uuid,
    key,
    value_string,
    value_numeric,
    value_bool,
    value_datetime,
    _timestamp,
    _offset,
    _partition
FROM {kafka_table_name}
""".format(
        mv_name=EVENT_PROPERTIES_MV,
        writable_table_name=EVENT_PROPERTIES_WRITABLE_TABLE,
        kafka_table_name=EVENT_PROPERTIES_KAFKA_TABLE,
    )
