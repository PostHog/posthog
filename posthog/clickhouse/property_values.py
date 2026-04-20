from django.conf import settings

from posthog.clickhouse.table_engines import AggregatingMergeTree, Distributed, ReplicationScheme

TABLE_NAME = "property_values"
WRITABLE_TABLE_NAME = f"writable_{TABLE_NAME}"
DISTRIBUTED_TABLE_NAME = f"{TABLE_NAME}_distributed"
MV_NAME = f"{TABLE_NAME}_mv"

PROPERTY_VALUES_TABLE_BASE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name}
(
    `team_id` Int64 CODEC(DoubleDelta, ZSTD(1)),
    `property_type` LowCardinality(String) CODEC(ZSTD(1)),
    `property_key` LowCardinality(String) CODEC(ZSTD(1)),
    `property_value` String CODEC(ZSTD(1)),
    `property_count` SimpleAggregateFunction(sum, UInt64),
    `last_seen` SimpleAggregateFunction(max, DateTime) DEFAULT now()
    {extra_fields}
) ENGINE = {engine}
"""


def PROPERTY_VALUES_TABLE_SQL() -> str:
    return (
        PROPERTY_VALUES_TABLE_BASE_SQL
        + """
ORDER BY (team_id, property_type, property_key, property_value)
TTL last_seen + INTERVAL 7 DAY DELETE
SETTINGS
    index_granularity = 8192,
    enable_full_text_index = 1
"""
    ).format(
        table_name=TABLE_NAME,
        engine=AggregatingMergeTree(TABLE_NAME, replication_scheme=ReplicationScheme.REPLICATED),
        extra_fields=""",
    INDEX idx_property_value property_value TYPE text(tokenizer = ngrams(3)) GRANULARITY 1""",
    )


def WRITABLE_PROPERTY_VALUES_TABLE_SQL() -> str:
    return PROPERTY_VALUES_TABLE_BASE_SQL.format(
        table_name=WRITABLE_TABLE_NAME,
        engine=Distributed(
            data_table=TABLE_NAME,
            cluster=settings.CLICKHOUSE_AUX_CLUSTER,
        ),
        extra_fields="",
    )


def PROPERTY_VALUES_MV_SQL() -> str:
    return """
CREATE MATERIALIZED VIEW IF NOT EXISTS {mv_name}
TO {writable_table}
AS SELECT
    team_id,
    tuple.1 as property_type,
    tuple.2 as property_key,
    tuple.3 as property_value,
    sumSimpleState(toUInt64(1)) as property_count,
    maxSimpleState(toDateTime(timestamp)) as last_seen
FROM {database}.sharded_events
ARRAY JOIN
    arrayConcat(
        arrayMap(kv -> ('event', kv.1, kv.2), JSONExtractKeysAndValues(properties, 'String')),
        arrayMap(kv -> ('person', kv.1, kv.2), JSONExtractKeysAndValues(person_properties, 'String')),
        arrayMap(kv -> ('group_0', kv.1, kv.2), JSONExtractKeysAndValues(group0_properties, 'String')),
        arrayMap(kv -> ('group_1', kv.1, kv.2), JSONExtractKeysAndValues(group1_properties, 'String')),
        arrayMap(kv -> ('group_2', kv.1, kv.2), JSONExtractKeysAndValues(group2_properties, 'String')),
        arrayMap(kv -> ('group_3', kv.1, kv.2), JSONExtractKeysAndValues(group3_properties, 'String')),
        arrayMap(kv -> ('group_4', kv.1, kv.2), JSONExtractKeysAndValues(group4_properties, 'String'))
    ) as tuple
WHERE length(tuple.2) > 0
  AND length(tuple.2) <= 400
  AND length(tuple.3) > 0
  AND length(tuple.3) < 256
GROUP BY team_id, property_type, property_key, property_value
""".format(
        mv_name=MV_NAME,
        writable_table=WRITABLE_TABLE_NAME,
        database=settings.CLICKHOUSE_DATABASE,
    )


def DISTRIBUTED_PROPERTY_VALUES_TABLE_SQL() -> str:
    return PROPERTY_VALUES_TABLE_BASE_SQL.format(
        table_name=DISTRIBUTED_TABLE_NAME,
        engine=Distributed(
            data_table=TABLE_NAME,
            cluster=settings.CLICKHOUSE_AUX_CLUSTER,
        ),
        extra_fields="",
    )
