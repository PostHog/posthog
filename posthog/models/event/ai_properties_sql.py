from django.conf import settings

from posthog.clickhouse.cluster import ON_CLUSTER_CLAUSE
from posthog.clickhouse.kafka_engine import (
    CONSUMER_GROUP_AI_EVENT_PROPERTIES,
    KAFKA_COLUMNS,
    STORAGE_POLICY,
    kafka_engine,
)
from posthog.clickhouse.table_engines import Distributed, ReplacingMergeTree, ReplicationScheme
from posthog.kafka_client.topics import KAFKA_CLICKHOUSE_AI_EVENT_PROPERTIES

AI_EVENT_TYPES = (
    "'$ai_generation'",
    "'$ai_span'",
    "'$ai_trace'",
    "'$ai_embedding'",
    "'$ai_metric'",
    "'$ai_feedback'",
)
AI_EVENT_TYPES_CLAUSE = f"({', '.join(AI_EVENT_TYPES)})"

AI_LARGE_PROPERTIES = (
    "$ai_input",
    "$ai_output",
    "$ai_output_choices",
    "$ai_input_state",
    "$ai_output_state",
    "$ai_tools",
)


def SHARDED_AI_EVENT_PROPERTIES_DATA_TABLE():
    return "sharded_ai_event_properties"


def WRITABLE_AI_EVENT_PROPERTIES_TABLE_NAME():
    return "writable_ai_event_properties"


def AI_EVENT_PROPERTIES_TABLE_NAME():
    return "ai_event_properties"


AI_EVENT_PROPERTIES_TABLE_BASE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name} {on_cluster_clause}
(
    uuid UUID,
    team_id Int64,
    timestamp DateTime64(6, 'UTC'),
    ai_input String CODEC(ZSTD(3)),
    ai_output String CODEC(ZSTD(3)),
    ai_output_choices String CODEC(ZSTD(3)),
    ai_input_state String CODEC(ZSTD(3)),
    ai_output_state String CODEC(ZSTD(3)),
    ai_tools String CODEC(ZSTD(3))
    {extra_fields}
) ENGINE = {engine}
"""


def SHARDED_AI_EVENT_PROPERTIES_TABLE_SQL():
    return (
        AI_EVENT_PROPERTIES_TABLE_BASE_SQL
        + """PARTITION BY toStartOfDay(timestamp)
ORDER BY (team_id, toDate(timestamp), uuid)
TTL toDateTime(timestamp) + INTERVAL 30 DAY
SETTINGS ttl_only_drop_parts = 1
{storage_policy}
"""
    ).format(
        table_name=SHARDED_AI_EVENT_PROPERTIES_DATA_TABLE(),
        on_cluster_clause=ON_CLUSTER_CLAUSE(False),
        engine=ReplacingMergeTree(
            "ai_event_properties", ver="_timestamp", replication_scheme=ReplicationScheme.SHARDED
        ),
        extra_fields=KAFKA_COLUMNS,
        storage_policy=STORAGE_POLICY(),
    )


def DISTRIBUTED_AI_EVENT_PROPERTIES_TABLE_SQL():
    return AI_EVENT_PROPERTIES_TABLE_BASE_SQL.format(
        table_name=AI_EVENT_PROPERTIES_TABLE_NAME(),
        on_cluster_clause=ON_CLUSTER_CLAUSE(),
        engine=Distributed(
            data_table=SHARDED_AI_EVENT_PROPERTIES_DATA_TABLE(),
            sharding_key="sipHash64(toString(uuid))",
        ),
        extra_fields=KAFKA_COLUMNS,
    )


def WRITABLE_AI_EVENT_PROPERTIES_TABLE_SQL():
    return AI_EVENT_PROPERTIES_TABLE_BASE_SQL.format(
        table_name=WRITABLE_AI_EVENT_PROPERTIES_TABLE_NAME(),
        on_cluster_clause=ON_CLUSTER_CLAUSE(False),
        engine=Distributed(
            data_table=SHARDED_AI_EVENT_PROPERTIES_DATA_TABLE(),
            sharding_key="sipHash64(toString(uuid))",
            cluster=settings.CLICKHOUSE_WRITABLE_CLUSTER,
        ),
        extra_fields=KAFKA_COLUMNS,
    )


def KAFKA_AI_EVENT_PROPERTIES_TABLE_SQL():
    return AI_EVENT_PROPERTIES_TABLE_BASE_SQL.format(
        table_name="kafka_ai_event_properties",
        on_cluster_clause="",
        engine=kafka_engine(
            topic=KAFKA_CLICKHOUSE_AI_EVENT_PROPERTIES,
            group=CONSUMER_GROUP_AI_EVENT_PROPERTIES,
        ),
        extra_fields="",
    )


def AI_EVENT_PROPERTIES_MV_SQL():
    return """
CREATE MATERIALIZED VIEW IF NOT EXISTS ai_event_properties_json_mv
TO {database}.{target_table}
AS SELECT
    uuid,
    team_id,
    timestamp,
    ai_input,
    ai_output,
    ai_output_choices,
    ai_input_state,
    ai_output_state,
    ai_tools,
    _timestamp,
    _offset
FROM {database}.kafka_ai_event_properties
""".format(
        target_table=WRITABLE_AI_EVENT_PROPERTIES_TABLE_NAME(),
        database=settings.CLICKHOUSE_DATABASE,
    )


def DROP_AI_EVENT_PROPERTIES_MV_SQL():
    return "DROP TABLE IF EXISTS ai_event_properties_json_mv"


def DROP_KAFKA_AI_EVENT_PROPERTIES_TABLE_SQL():
    return "DROP TABLE IF EXISTS kafka_ai_event_properties"


def DROP_SHARDED_AI_EVENT_PROPERTIES_TABLE_SQL():
    return f"DROP TABLE IF EXISTS {SHARDED_AI_EVENT_PROPERTIES_DATA_TABLE()}"


def DROP_DISTRIBUTED_AI_EVENT_PROPERTIES_TABLE_SQL():
    return f"DROP TABLE IF EXISTS {AI_EVENT_PROPERTIES_TABLE_NAME()} {ON_CLUSTER_CLAUSE()}"


def DROP_WRITABLE_AI_EVENT_PROPERTIES_TABLE_SQL():
    return f"DROP TABLE IF EXISTS {WRITABLE_AI_EVENT_PROPERTIES_TABLE_NAME()}"
