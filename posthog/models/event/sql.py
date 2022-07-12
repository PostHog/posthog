from django.conf import settings

from posthog.clickhouse.kafka_engine import (
    COPY_ROWS_BETWEEN_TEAMS_BASE_SQL,
    KAFKA_COLUMNS,
    STORAGE_POLICY,
    kafka_engine,
    trim_quotes_expr,
)
from posthog.clickhouse.table_engines import Distributed, ReplacingMergeTree, ReplicationScheme
from posthog.kafka_client.topics import KAFKA_EVENTS, KAFKA_EVENTS_JSON

EVENTS_DATA_TABLE = lambda: "sharded_events" if settings.CLICKHOUSE_REPLICATION else "events"
WRITABLE_EVENTS_DATA_TABLE = lambda: "writable_events" if settings.CLICKHOUSE_REPLICATION else EVENTS_DATA_TABLE()

TRUNCATE_EVENTS_TABLE_SQL = (
    lambda: f"TRUNCATE TABLE IF EXISTS {EVENTS_DATA_TABLE()} ON CLUSTER '{settings.CLICKHOUSE_CLUSTER}'"
)
DROP_EVENTS_TABLE_SQL = lambda: f"DROP TABLE IF EXISTS {EVENTS_DATA_TABLE()} ON CLUSTER '{settings.CLICKHOUSE_CLUSTER}'"

EVENTS_TABLE_BASE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name} ON CLUSTER '{cluster}'
(
    uuid UUID,
    event VARCHAR,
    properties VARCHAR,
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
    group4_created_at DateTime64
    {materialized_columns}
    {extra_fields}
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
"""

EVENTS_TABLE_PROXY_MATERIALIZED_COLUMNS = """
    , $group_0 VARCHAR COMMENT 'column_materializer::$group_0'
    , $group_1 VARCHAR COMMENT 'column_materializer::$group_1'
    , $group_2 VARCHAR COMMENT 'column_materializer::$group_2'
    , $group_3 VARCHAR COMMENT 'column_materializer::$group_3'
    , $group_4 VARCHAR COMMENT 'column_materializer::$group_4'
    , $window_id VARCHAR COMMENT 'column_materializer::$window_id'
    , $session_id VARCHAR COMMENT 'column_materializer::$session_id'
"""

EVENTS_DATA_TABLE_ENGINE = lambda: ReplacingMergeTree(
    "events", ver="_timestamp", replication_scheme=ReplicationScheme.SHARDED,
)
EVENTS_TABLE_SQL = lambda: (
    EVENTS_TABLE_BASE_SQL
    + """PARTITION BY toYYYYMM(timestamp)
ORDER BY (team_id, toDate(timestamp), event, cityHash64(distinct_id), cityHash64(uuid))
{sample_by}
{storage_policy}
"""
).format(
    table_name=EVENTS_DATA_TABLE(),
    cluster=settings.CLICKHOUSE_CLUSTER,
    engine=EVENTS_DATA_TABLE_ENGINE(),
    extra_fields=KAFKA_COLUMNS,
    materialized_columns=EVENTS_TABLE_MATERIALIZED_COLUMNS,
    sample_by="SAMPLE BY cityHash64(distinct_id)",
    storage_policy=STORAGE_POLICY(),
)

# DEPRECATED
# Use KAFKA_EVENTS_TABLE_JSON_SQL instead
# We cannot remove this code yet for backwards compatibility while moving to the new table
KAFKA_EVENTS_TABLE_SQL = lambda: EVENTS_TABLE_BASE_SQL.format(
    table_name="kafka_events",
    cluster=settings.CLICKHOUSE_CLUSTER,
    engine=kafka_engine(topic=KAFKA_EVENTS, serialization="Protobuf", proto_schema="events:Event"),
    extra_fields="",
    materialized_columns="",
)

# DEPRECATED
# Use EVENTS_TABLE_JSON_MV_SQL instead
# We cannot remove this code yet for backwards compatibility while moving to the new table
EVENTS_TABLE_MV_SQL = lambda: """
CREATE MATERIALIZED VIEW events_mv ON CLUSTER '{cluster}'
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
_timestamp,
_offset
FROM {database}.kafka_events
""".format(
    target_table=WRITABLE_EVENTS_DATA_TABLE(),
    cluster=settings.CLICKHOUSE_CLUSTER,
    database=settings.CLICKHOUSE_DATABASE,
)

# we add the settings to prevent poison pills from stopping ingestion
# kafka_skip_broken_messages is an int, not a boolean, so we explicitly set
# the max block size to consume from kafka such that we skip _all_ broken messages
# this is an added safety mechanism given we control payloads to this topic
KAFKA_EVENTS_TABLE_JSON_SQL = lambda: (
    EVENTS_TABLE_BASE_SQL
    + """
    SETTINGS kafka_skip_broken_messages = 100
"""
).format(
    table_name="kafka_events_json",
    cluster=settings.CLICKHOUSE_CLUSTER,
    engine=kafka_engine(topic=KAFKA_EVENTS_JSON),
    extra_fields="",
    materialized_columns="",
)

EVENTS_TABLE_JSON_MV_SQL = lambda: """
CREATE MATERIALIZED VIEW events_json_mv ON CLUSTER '{cluster}'
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
_timestamp,
_offset
FROM {database}.kafka_events_json
""".format(
    target_table=WRITABLE_EVENTS_DATA_TABLE(),
    cluster=settings.CLICKHOUSE_CLUSTER,
    database=settings.CLICKHOUSE_DATABASE,
)

# Distributed engine tables are only created if CLICKHOUSE_REPLICATED

# This table is responsible for writing to sharded_events based on a sharding key.
WRITABLE_EVENTS_TABLE_SQL = lambda: EVENTS_TABLE_BASE_SQL.format(
    table_name="writable_events",
    cluster=settings.CLICKHOUSE_CLUSTER,
    engine=Distributed(data_table=EVENTS_DATA_TABLE(), sharding_key="sipHash64(distinct_id)"),
    extra_fields=KAFKA_COLUMNS,
    materialized_columns="",
)

# This table is responsible for reading from events on a cluster setting
DISTRIBUTED_EVENTS_TABLE_SQL = lambda: EVENTS_TABLE_BASE_SQL.format(
    table_name="events",
    cluster=settings.CLICKHOUSE_CLUSTER,
    engine=Distributed(data_table=EVENTS_DATA_TABLE(), sharding_key="sipHash64(distinct_id)"),
    extra_fields=KAFKA_COLUMNS,
    materialized_columns=EVENTS_TABLE_PROXY_MATERIALIZED_COLUMNS,
)

INSERT_EVENT_SQL = (
    lambda: f"""
INSERT INTO {EVENTS_DATA_TABLE()} (uuid, event, properties, timestamp, team_id, distinct_id, elements_chain, created_at, _timestamp, _offset)
VALUES (%(uuid)s, %(event)s, %(properties)s, %(timestamp)s, %(team_id)s, %(distinct_id)s, %(elements_chain)s, %(created_at)s, now(), 0)
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
    created_at,
    _timestamp,
    _offset
)
VALUES
"""
)

GET_EVENTS_SQL = """
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
"""

GET_EVENTS_BY_TEAM_SQL = """
SELECT
    uuid,
    event,
    properties,
    timestamp,
    team_id,
    distinct_id,
    elements_chain,
    created_at
FROM events WHERE team_id = %(team_id)s
"""

SELECT_PROP_VALUES_SQL = """
SELECT
    DISTINCT {property_field}
FROM
    events
WHERE
    team_id = %(team_id)s AND
    JSONHas(properties, %(key)s)
    {parsed_date_from}
    {parsed_date_to}
LIMIT 10
"""

SELECT_PROP_VALUES_SQL_WITH_FILTER = """
SELECT
    DISTINCT {property_field}
FROM
    events
WHERE
    team_id = %(team_id)s AND
    {property_field} ILIKE %(value)s
    {parsed_date_from}
    {parsed_date_to}
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
SELECT toUInt16(0) AS total, {trunc_func}(toDateTime(%(date_to)s) - {interval_func}(number), {start_of_week_fix} %(timezone)s) AS day_start

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
FROM numbers(dateDiff(%(interval)s, {trunc_func}(toDateTime(%(date_from)s), {start_of_week_fix} %(timezone)s), toDateTime(%(date_to)s), %(timezone)s))

UNION ALL

-- Make sure we capture the interval date_from falls into.
SELECT toUInt16(0) AS total, {trunc_func}(toDateTime(%(date_from)s), {start_of_week_fix} %(timezone)s)
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
""".format(
    tag_regex=EXTRACT_TAG_REGEX, text_regex=EXTRACT_TEXT_REGEX,
)

GET_CUSTOM_EVENTS = """
SELECT DISTINCT event FROM events where team_id = %(team_id)s AND event NOT IN ['$autocapture', '$pageview', '$identify', '$pageleave', '$screen']
"""

GET_EVENTS_VOLUME = "SELECT event, count() AS count, max(timestamp) AS last_seen_at FROM events WHERE team_id = %(team_id)s AND timestamp > %(timestamp)s GROUP BY event ORDER BY count DESC"

GET_TOTAL_EVENTS_VOLUME = "SELECT count() AS count FROM events WHERE team_id = %(team_id)s"

#
# Copying demo data
#

COPY_EVENTS_BETWEEN_TEAMS = COPY_ROWS_BETWEEN_TEAMS_BASE_SQL.format(
    table_name=WRITABLE_EVENTS_DATA_TABLE(),
    columns_except_team_id="""uuid, event, properties, timestamp, distinct_id, elements_chain, created_at, person_id, person_created_at,
    person_properties, group0_properties, group1_properties, group2_properties, group3_properties, group4_properties,
     group0_created_at, group1_created_at, group2_created_at, group3_created_at, group4_created_at""",
)
