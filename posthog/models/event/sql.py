from django.conf import settings

from posthog.clickhouse.base_sql import COPY_ROWS_BETWEEN_TEAMS_BASE_SQL
from posthog.clickhouse.cluster import ON_CLUSTER_CLAUSE
from posthog.clickhouse.indexes import index_by_kafka_timestamp
from posthog.clickhouse.kafka_engine import (
    KAFKA_COLUMNS,
    KAFKA_COLUMNS_WITH_PARTITION,
    KAFKA_TIMESTAMP_MS_COLUMN,
    STORAGE_POLICY,
    kafka_engine,
    trim_quotes_expr,
)
from posthog.clickhouse.property_groups import property_groups
from posthog.clickhouse.table_engines import Distributed, ReplacingMergeTree, ReplicationScheme
from posthog.kafka_client.topics import KAFKA_EVENTS_JSON


def EVENTS_DATA_TABLE():
    return "sharded_events"


def WRITABLE_EVENTS_DATA_TABLE():
    return "writable_events"


def EVENTS_RECENT_DATA_TABLE():
    return "events_recent"


def TRUNCATE_EVENTS_TABLE_SQL():
    return f"TRUNCATE TABLE IF EXISTS {EVENTS_DATA_TABLE()} {ON_CLUSTER_CLAUSE()}"


TRUNCATE_EVENTS_RECENT_TABLE_SQL = (
    lambda: f"TRUNCATE TABLE IF EXISTS {EVENTS_RECENT_DATA_TABLE()} {ON_CLUSTER_CLAUSE()}"
)


def DROP_EVENTS_TABLE_SQL():
    return f"DROP TABLE IF EXISTS {EVENTS_DATA_TABLE()} {ON_CLUSTER_CLAUSE()}"


def DROP_KAFKA_EVENTS_RECENT_TABLE_SQL():
    return f"DROP TABLE IF EXISTS kafka_events_recent_json"


def DROP_EVENTS_RECENT_MV_TABLE_SQL():
    return f"DROP TABLE IF EXISTS events_recent_json_mv"


DROP_DISTRIBUTED_EVENTS_TABLE_SQL = f"DROP TABLE IF EXISTS events {ON_CLUSTER_CLAUSE()}"

INSERTED_AT_COLUMN = ", inserted_at Nullable(DateTime64(6, 'UTC')) DEFAULT NOW64()"
INSERTED_AT_NOT_NULLABLE_COLUMN = ", inserted_at DateTime64(6, 'UTC') DEFAULT NOW64()"
KAFKA_CONSUMER_BREADCRUMBS_COLUMN = ", consumer_breadcrumbs Array(String)"

EVENTS_TABLE_BASE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name} {on_cluster_clause}
(
    uuid UUID,
    event VARCHAR,
    properties VARCHAR CODEC(ZSTD(3)),
    timestamp DateTime64(6, 'UTC'),
    team_id Int64,
    distinct_id VARCHAR,
    elements_chain VARCHAR,
    created_at DateTime64(6, 'UTC'),
    person_id UUID,
    person_created_at DateTime64,
    person_properties VARCHAR Codec(ZSTD(3)),
    group0_properties VARCHAR Codec(ZSTD(3)),
    group1_properties VARCHAR Codec(ZSTD(3)),
    group2_properties VARCHAR Codec(ZSTD(3)),
    group3_properties VARCHAR Codec(ZSTD(3)),
    group4_properties VARCHAR Codec(ZSTD(3)),
    group0_created_at DateTime64,
    group1_created_at DateTime64,
    group2_created_at DateTime64,
    group3_created_at DateTime64,
    group4_created_at DateTime64,
    person_mode Enum8('full' = 0, 'propertyless' = 1, 'force_upgrade' = 2)
    {materialized_columns}
    {extra_fields}
    {indexes}
) ENGINE = {engine}
"""

EVENTS_TABLE_MATERIALIZED_COLUMNS = f"""
    , $group_0 VARCHAR MATERIALIZED {trim_quotes_expr("JSONExtractRaw(properties, '$group_0')")} COMMENT 'column_materializer::$group_0'
    , $group_1 VARCHAR MATERIALIZED {trim_quotes_expr("JSONExtractRaw(properties, '$group_1')")} COMMENT 'column_materializer::$group_1'
    , $group_2 VARCHAR MATERIALIZED {trim_quotes_expr("JSONExtractRaw(properties, '$group_2')")} COMMENT 'column_materializer::$group_2'
    , $group_3 VARCHAR MATERIALIZED {trim_quotes_expr("JSONExtractRaw(properties, '$group_3')")} COMMENT 'column_materializer::$group_3'
    , $group_4 VARCHAR MATERIALIZED {trim_quotes_expr("JSONExtractRaw(properties, '$group_4')")} COMMENT 'column_materializer::$group_4'
    , $window_id VARCHAR MATERIALIZED {trim_quotes_expr("JSONExtractRaw(properties, '$window_id')")} COMMENT 'column_materializer::$window_id'
    , $session_id VARCHAR MATERIALIZED {trim_quotes_expr("JSONExtractRaw(properties, '$session_id')")} COMMENT 'column_materializer::$session_id'
    , $session_id_uuid Nullable(UInt128) MATERIALIZED toUInt128(JSONExtract(properties, '$session_id', 'Nullable(UUID)'))
    , elements_chain_href String MATERIALIZED extract(elements_chain, '(?::|\")href="(.*?)"')
    , elements_chain_texts Array(String) MATERIALIZED arrayDistinct(extractAll(elements_chain, '(?::|\")text="(.*?)"'))
    , elements_chain_ids Array(String) MATERIALIZED arrayDistinct(extractAll(elements_chain, '(?::|\")attr_id="(.*?)"'))
    , elements_chain_elements Array(Enum('a', 'button', 'form', 'input', 'select', 'textarea', 'label')) MATERIALIZED arrayDistinct(extractAll(elements_chain, '(?:^|;)(a|button|form|input|select|textarea|label)(?:\\.|$|:)'))
    , `mat_$ai_is_error` Nullable(String) MATERIALIZED JSONExtract(properties, '$ai_is_error', 'Nullable(String)') COMMENT 'column_materializer::properties::$ai_is_error'
    , INDEX `bloom_filter_$ai_is_error` `mat_$ai_is_error` TYPE bloom_filter GRANULARITY 1
    , INDEX `minmax_$group_0` `$group_0` TYPE minmax GRANULARITY 1
    , INDEX `minmax_$group_1` `$group_1` TYPE minmax GRANULARITY 1
    , INDEX `minmax_$group_2` `$group_2` TYPE minmax GRANULARITY 1
    , INDEX `minmax_$group_3` `$group_3` TYPE minmax GRANULARITY 1
    , INDEX `minmax_$group_4` `$group_4` TYPE minmax GRANULARITY 1
    , INDEX `minmax_$window_id` `$window_id` TYPE minmax GRANULARITY 1
    , INDEX `minmax_$session_id` `$session_id` TYPE minmax GRANULARITY 1
    , {", ".join(property_groups.get_create_table_pieces("sharded_events"))}
"""

EVENTS_TABLE_PROXY_MATERIALIZED_COLUMNS = f"""
    , $group_0 VARCHAR COMMENT 'column_materializer::$group_0'
    , $group_1 VARCHAR COMMENT 'column_materializer::$group_1'
    , $group_2 VARCHAR COMMENT 'column_materializer::$group_2'
    , $group_3 VARCHAR COMMENT 'column_materializer::$group_3'
    , $group_4 VARCHAR COMMENT 'column_materializer::$group_4'
    , $window_id VARCHAR COMMENT 'column_materializer::$window_id'
    , $session_id VARCHAR COMMENT 'column_materializer::$session_id'
    , $session_id_uuid Nullable(UInt128)
    , elements_chain_href String COMMENT 'column_materializer::elements_chain::href'
    , elements_chain_texts Array(String) COMMENT 'column_materializer::elements_chain::texts'
    , elements_chain_ids Array(String) COMMENT 'column_materializer::elements_chain::ids'
    , elements_chain_elements Array(Enum('a', 'button', 'form', 'input', 'select', 'textarea', 'label')) COMMENT 'column_materializer::elements_chain::elements'
    , `mat_$ai_is_error` Nullable(String) COMMENT 'column_materializer::properties::$ai_is_error'
    , {", ".join(property_groups.get_create_table_pieces("events"))}
"""


def EVENTS_DATA_TABLE_ENGINE():
    return ReplacingMergeTree("events", ver="_timestamp", replication_scheme=ReplicationScheme.SHARDED)


def EVENTS_TABLE_SQL():
    return (
        EVENTS_TABLE_BASE_SQL
        + """PARTITION BY toYYYYMM(timestamp)
ORDER BY (team_id, toDate(timestamp), event, cityHash64(distinct_id), cityHash64(uuid))
{sample_by}
{storage_policy}
"""
    ).format(
        table_name=EVENTS_DATA_TABLE(),
        on_cluster_clause=ON_CLUSTER_CLAUSE(),
        engine=EVENTS_DATA_TABLE_ENGINE(),
        extra_fields=KAFKA_COLUMNS + INSERTED_AT_COLUMN + KAFKA_CONSUMER_BREADCRUMBS_COLUMN,
        materialized_columns=EVENTS_TABLE_MATERIALIZED_COLUMNS,
        indexes=f"""
    , {index_by_kafka_timestamp(EVENTS_DATA_TABLE())}
    """,
        sample_by="SAMPLE BY cityHash64(distinct_id)",
        storage_policy=STORAGE_POLICY(),
    )


EVENTS_TABLE_INSERTED_AT_INDEX_SQL = """
ALTER TABLE {table_name} ON CLUSTER {cluster}
ADD INDEX `minmax_inserted_at` COALESCE(`inserted_at`, `_timestamp`)
TYPE minmax
GRANULARITY 1
""".format(table_name=EVENTS_DATA_TABLE(), cluster=settings.CLICKHOUSE_CLUSTER)

EVENTS_TABLE_MATERIALIZE_INSERTED_AT_INDEX_SQL = """
ALTER TABLE {table_name} ON CLUSTER {cluster}
MATERIALIZE INDEX `minmax_inserted_at`
""".format(table_name=EVENTS_DATA_TABLE(), cluster=settings.CLICKHOUSE_CLUSTER)

# we add the settings to prevent poison pills from stopping ingestion
# kafka_skip_broken_messages is an int, not a boolean, so we explicitly set
# the max block size to consume from kafka such that we skip _all_ broken messages
# this is an added safety mechanism given we control payloads to this topic


def KAFKA_EVENTS_TABLE_JSON_SQL():
    return (
        EVENTS_TABLE_BASE_SQL
        + """
    SETTINGS kafka_skip_broken_messages = 100
"""
    ).format(
        table_name="kafka_events_json",
        on_cluster_clause=ON_CLUSTER_CLAUSE(),
        engine=kafka_engine(topic=KAFKA_EVENTS_JSON),
        extra_fields="",
        materialized_columns="",
        indexes="",
    )


EVENTS_TABLE_JSON_MV_SQL = (
    lambda: """
CREATE MATERIALIZED VIEW IF NOT EXISTS events_json_mv ON CLUSTER '{cluster}'
TO {database}.{target_table}
AS SELECT
uuid,
event,
properties,
timestamp,
team_id,
distinct_id,
elements_chain,
created_at,
person_id,
person_created_at,
person_properties,
group0_properties,
group1_properties,
group2_properties,
group3_properties,
group4_properties,
group0_created_at,
group1_created_at,
group2_created_at,
group3_created_at,
group4_created_at,
person_mode,
_timestamp,
_offset,
arrayMap(
    i -> _headers.value[i],
    arrayFilter(
        i -> _headers.name[i] = 'kafka-consumer-breadcrumbs',
        arrayEnumerate(_headers.name)
    )
) as consumer_breadcrumbs
FROM {database}.kafka_events_json
""".format(
        target_table=WRITABLE_EVENTS_DATA_TABLE(),
        cluster=settings.CLICKHOUSE_CLUSTER,
        database=settings.CLICKHOUSE_DATABASE,
    )
)


def KAFKA_EVENTS_RECENT_TABLE_JSON_SQL(on_cluster=True):
    return (
        EVENTS_TABLE_BASE_SQL
        + """
    SETTINGS kafka_skip_broken_messages = 100,  kafka_num_consumers = 2, kafka_thread_per_consumer = 1
"""
    ).format(
        table_name="kafka_events_recent_json",
        on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster),
        engine=kafka_engine(topic=KAFKA_EVENTS_JSON, group="group1_recent"),
        extra_fields="",
        materialized_columns="",
        indexes="",
    )


EVENTS_RECENT_TABLE_JSON_MV_SQL = (
    lambda target_table="writable_events_recent": """
CREATE MATERIALIZED VIEW IF NOT EXISTS events_recent_json_mv
TO {database}.{target_table}
AS SELECT
uuid,
event,
properties,
timestamp,
team_id,
distinct_id,
elements_chain,
created_at,
person_id,
person_created_at,
person_properties,
group0_properties,
group1_properties,
group2_properties,
group3_properties,
group4_properties,
group0_created_at,
group1_created_at,
group2_created_at,
group3_created_at,
group4_created_at,
person_mode,
_timestamp,
_timestamp_ms,
_offset,
_partition
FROM {database}.kafka_events_recent_json
""".format(
        target_table=target_table,
        database=settings.CLICKHOUSE_DATABASE,
    )
)


def EVENTS_RECENT_TABLE_SQL(on_cluster=True):
    return (
        EVENTS_TABLE_BASE_SQL
        + """PARTITION BY toStartOfHour(inserted_at)
ORDER BY (team_id, toStartOfHour(inserted_at), event, cityHash64(distinct_id), cityHash64(uuid))
TTL toDateTime(inserted_at) + INTERVAL 7 DAY
{storage_policy}
"""
    ).format(
        table_name=EVENTS_RECENT_DATA_TABLE(),
        on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster),
        engine=ReplacingMergeTree(EVENTS_RECENT_DATA_TABLE(), ver="_timestamp"),
        extra_fields=KAFKA_COLUMNS_WITH_PARTITION + INSERTED_AT_NOT_NULLABLE_COLUMN + f", {KAFKA_TIMESTAMP_MS_COLUMN}",
        materialized_columns="",
        indexes="",
        storage_policy=STORAGE_POLICY(),
    )


def DISTRIBUTED_EVENTS_RECENT_TABLE_SQL(on_cluster=True):
    return EVENTS_TABLE_BASE_SQL.format(
        table_name="distributed_events_recent",
        on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster),
        engine=Distributed(
            data_table=EVENTS_RECENT_DATA_TABLE(),
            sharding_key="sipHash64(distinct_id)",
            cluster=settings.CLICKHOUSE_SINGLE_SHARD_CLUSTER,
        ),
        extra_fields=KAFKA_COLUMNS_WITH_PARTITION + INSERTED_AT_COLUMN + f", {KAFKA_TIMESTAMP_MS_COLUMN}",
        materialized_columns="",
        indexes="",
    )


def WRITABLE_EVENTS_RECENT_TABLE_SQL(on_cluster=True):
    return EVENTS_TABLE_BASE_SQL.format(
        table_name="writable_events_recent",
        on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster),
        engine=Distributed(
            data_table=EVENTS_RECENT_DATA_TABLE(),
            cluster=settings.CLICKHOUSE_BATCH_EXPORTS_CLUSTER,
        ),
        extra_fields=KAFKA_COLUMNS_WITH_PARTITION + f", {KAFKA_TIMESTAMP_MS_COLUMN}",
        materialized_columns="",
        indexes="",
    )


# Distributed engine tables are only created if CLICKHOUSE_REPLICATED

# This table is responsible for writing to sharded_events based on a sharding key.


def WRITABLE_EVENTS_TABLE_SQL():
    return EVENTS_TABLE_BASE_SQL.format(
        table_name="writable_events",
        on_cluster_clause=ON_CLUSTER_CLAUSE(),
        engine=Distributed(data_table=EVENTS_DATA_TABLE(), sharding_key="sipHash64(distinct_id)"),
        extra_fields=KAFKA_COLUMNS + KAFKA_CONSUMER_BREADCRUMBS_COLUMN,
        materialized_columns="",
        indexes="",
    )


# This table is responsible for reading from events on a cluster setting


def DISTRIBUTED_EVENTS_TABLE_SQL(on_cluster=True):
    return EVENTS_TABLE_BASE_SQL.format(
        table_name="events",
        on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster),
        engine=Distributed(data_table=EVENTS_DATA_TABLE(), sharding_key="sipHash64(distinct_id)"),
        extra_fields=KAFKA_COLUMNS + INSERTED_AT_COLUMN + KAFKA_CONSUMER_BREADCRUMBS_COLUMN,
        materialized_columns=EVENTS_TABLE_PROXY_MATERIALIZED_COLUMNS,
        indexes="",
    )


INSERT_EVENT_SQL = (
    lambda: f"""
INSERT INTO {EVENTS_DATA_TABLE()}
(
    uuid,
    event,
    properties,
    timestamp,
    team_id,
    distinct_id,
    elements_chain,
    person_id,
    person_properties,
    person_created_at,
    group0_properties,
    group1_properties,
    group2_properties,
    group3_properties,
    group4_properties,
    group0_created_at,
    group1_created_at,
    group2_created_at,
    group3_created_at,
    group4_created_at,
    person_mode,
    created_at,
    _timestamp,
    _offset
)
VALUES
(
    %(uuid)s,
    %(event)s,
    %(properties)s,
    %(timestamp)s,
    %(team_id)s,
    %(distinct_id)s,
    %(elements_chain)s,
    %(person_id)s,
    %(person_properties)s,
    %(person_created_at)s,
    %(group0_properties)s,
    %(group1_properties)s,
    %(group2_properties)s,
    %(group3_properties)s,
    %(group4_properties)s,
    %(group0_created_at)s,
    %(group1_created_at)s,
    %(group2_created_at)s,
    %(group3_created_at)s,
    %(group4_created_at)s,
    %(person_mode)s,
    %(created_at)s,
    now(),
    0
)
"""
)

BULK_INSERT_EVENT_SQL = (
    lambda: f"""
INSERT INTO {EVENTS_DATA_TABLE()}
(
    uuid,
    event,
    properties,
    timestamp,
    team_id,
    distinct_id,
    elements_chain,
    person_id,
    person_properties,
    person_created_at,
    group0_properties,
    group1_properties,
    group2_properties,
    group3_properties,
    group4_properties,
    group0_created_at,
    group1_created_at,
    group2_created_at,
    group3_created_at,
    group4_created_at,
    person_mode,
    created_at,
    _timestamp,
    _offset
)
VALUES
"""
)


SELECT_PROP_VALUES_SQL_WITH_FILTER = """
SELECT
    DISTINCT {property_field}
FROM
    events
WHERE
    team_id = %(team_id)s
    {property_exists_filter}
    {parsed_date_from}
    {parsed_date_to}
    {event_filter}
    {value_filter}
{order_by_clause}
LIMIT 10
"""

SELECT_EVENT_BY_TEAM_AND_CONDITIONS_SQL = """
SELECT
    uuid,
    event,
    properties,
    timestamp,
    team_id,
    distinct_id,
    elements_chain,
    created_at
FROM
    events
where team_id = %(team_id)s
{conditions}
ORDER BY timestamp {order} {limit}
"""

SELECT_EVENT_BY_TEAM_AND_CONDITIONS_FILTERS_SQL = """
SELECT
    uuid,
    event,
    properties,
    timestamp,
    team_id,
    distinct_id,
    elements_chain,
    created_at
FROM events
WHERE
team_id = %(team_id)s
{conditions}
{filters}
ORDER BY timestamp {order} {limit}
"""

SELECT_ONE_EVENT_SQL = """
SELECT
    uuid,
    event,
    properties,
    timestamp,
    team_id,
    distinct_id,
    elements_chain,
    created_at
FROM events WHERE uuid = %(event_id)s AND team_id = %(team_id)s
"""

NULL_SQL = """
-- Creates zero values for all date axis ticks for the given date_from, date_to range
SELECT toUInt16(0) AS total, {date_to_truncated} - {interval_func}(number) AS day_start

-- Get the number of `intervals` between date_from and date_to.
--
-- NOTE: for week there is some unusual behavior, see:
--       https://github.com/ClickHouse/ClickHouse/issues/7322
--
--       This actually aligns with what we want, as they are assuming Sunday week starts,
--       and we'd rather have the relative week num difference. Likewise the same for
--       "month" intervals
--
--       To ensure we get all relevant intervals, we add in the truncated "date_from"
--       value.
--
--       This behaviour of dateDiff is different to our handling of "week" and "month"
--       differences we are performing in python, which just considers seconds between
--       date_from and date_to
--
-- TODO: Ths pattern of generating intervals is repeated in several places. Reuse this
--       `ticks` query elsewhere.
FROM numbers(dateDiff(%(interval)s, {date_from_truncated}, toDateTime(%(date_to)s, %(timezone)s)))

UNION ALL

-- Make sure we capture the interval date_from falls into.
SELECT toUInt16(0) AS total, {date_from_truncated}
"""

EVENT_JOIN_PERSON_SQL = """
INNER JOIN ({GET_TEAM_PERSON_DISTINCT_IDS}) as pdi ON events.distinct_id = pdi.distinct_id
"""

GET_EVENTS_WITH_PROPERTIES = """
SELECT * FROM events WHERE
team_id = %(team_id)s
{filters}
{order_by}
"""

EXTRACT_TAG_REGEX = "extract(elements_chain, '^(.*?)[.|:]')"
EXTRACT_TEXT_REGEX = "extract(elements_chain, 'text=\"(.*?)\"')"

ELEMENT_TAG_COUNT = """
SELECT concat('<', {tag_regex}, '> ', {text_regex}) AS tag_name,
       events.elements_chain,
       count(*) as tag_count
FROM events
WHERE events.team_id = %(team_id)s AND event = '$autocapture'
GROUP BY tag_name, elements_chain
ORDER BY tag_count desc, tag_name
LIMIT %(limit)s
""".format(tag_regex=EXTRACT_TAG_REGEX, text_regex=EXTRACT_TEXT_REGEX)

GET_CUSTOM_EVENTS = """
SELECT DISTINCT event FROM events where team_id = %(team_id)s AND event NOT IN ['$autocapture', '$pageview', '$identify', '$pageleave', '$screen']
"""

#
# Demo data
#

COPY_EVENTS_BETWEEN_TEAMS = COPY_ROWS_BETWEEN_TEAMS_BASE_SQL.format(
    table_name=WRITABLE_EVENTS_DATA_TABLE(),
    columns_except_team_id="""uuid, event, properties, timestamp, distinct_id, elements_chain, created_at, person_id, person_created_at,
    person_properties, group0_properties, group1_properties, group2_properties, group3_properties, group4_properties,
     group0_created_at, group1_created_at, group2_created_at, group3_created_at, group4_created_at, person_mode""",
)
