from ee.kafka_client.topics import KAFKA_EVENTS
from posthog.settings import CLICKHOUSE_CLUSTER, CLICKHOUSE_DATABASE, DEBUG

from .clickhouse import KAFKA_COLUMNS, REPLACING_MERGE_TREE, STORAGE_POLICY, kafka_engine, table_engine
from .person import GET_TEAM_PERSON_DISTINCT_IDS

EVENTS_TABLE = "events"

TRUNCATE_EVENTS_TABLE_SQL = f"TRUNCATE TABLE IF EXISTS {EVENTS_TABLE} ON CLUSTER {CLICKHOUSE_CLUSTER}"
DROP_EVENTS_TABLE_SQL = f"DROP TABLE IF EXISTS {EVENTS_TABLE} ON CLUSTER {CLICKHOUSE_CLUSTER}"

EVENTS_TABLE_BASE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name} ON CLUSTER {cluster}
(
    uuid UUID,
    event VARCHAR,
    properties VARCHAR,
    timestamp DateTime64(6, 'UTC'),
    team_id Int64,
    distinct_id VARCHAR,
    elements_chain VARCHAR,
    created_at DateTime64(6, 'UTC')
    {materialized_columns}
    {extra_fields}
) ENGINE = {engine}
"""

EVENTS_TABLE_MATERIALIZED_COLUMNS = """
    , $group_0 VARCHAR materialized trim(BOTH '\"' FROM JSONExtractRaw(properties, '$group_0')) COMMENT 'column_materializer::$group_0'
    , $group_1 VARCHAR materialized trim(BOTH '\"' FROM JSONExtractRaw(properties, '$group_1')) COMMENT 'column_materializer::$group_1'
    , $group_2 VARCHAR materialized trim(BOTH '\"' FROM JSONExtractRaw(properties, '$group_2')) COMMENT 'column_materializer::$group_2'
    , $group_3 VARCHAR materialized trim(BOTH '\"' FROM JSONExtractRaw(properties, '$group_3')) COMMENT 'column_materializer::$group_3'
    , $group_4 VARCHAR materialized trim(BOTH '\"' FROM JSONExtractRaw(properties, '$group_4')) COMMENT 'column_materializer::$group_4'
"""

EVENTS_TABLE_SQL = (
    EVENTS_TABLE_BASE_SQL
    + """PARTITION BY toYYYYMM(timestamp)
ORDER BY (team_id, toDate(timestamp), distinct_id, uuid)
{sample_by_uuid}
{storage_policy}
"""
).format(
    table_name=EVENTS_TABLE,
    cluster=CLICKHOUSE_CLUSTER,
    engine=table_engine(EVENTS_TABLE, "_timestamp", REPLACING_MERGE_TREE),
    extra_fields=KAFKA_COLUMNS,
    materialized_columns=EVENTS_TABLE_MATERIALIZED_COLUMNS,
    sample_by_uuid="SAMPLE BY uuid" if not DEBUG else "",  # https://github.com/PostHog/posthog/issues/5684
    storage_policy=STORAGE_POLICY,
)

KAFKA_EVENTS_TABLE_SQL = EVENTS_TABLE_BASE_SQL.format(
    table_name="kafka_" + EVENTS_TABLE,
    cluster=CLICKHOUSE_CLUSTER,
    engine=kafka_engine(topic=KAFKA_EVENTS, serialization="Protobuf", proto_schema="events:Event"),
    extra_fields="",
    materialized_columns="",
)

# You must include the database here because of a bug in clickhouse
# related to https://github.com/ClickHouse/ClickHouse/issues/10471
EVENTS_TABLE_MV_SQL = """
CREATE MATERIALIZED VIEW {table_name}_mv ON CLUSTER {cluster}
TO {database}.{table_name}
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
FROM {database}.kafka_{table_name}
""".format(
    table_name=EVENTS_TABLE, cluster=CLICKHOUSE_CLUSTER, database=CLICKHOUSE_DATABASE,
)

INSERT_EVENT_SQL = """
INSERT INTO events (uuid, event, properties, timestamp, team_id, distinct_id, elements_chain, created_at, _timestamp, _offset)
SELECT %(uuid)s, %(event)s, %(properties)s, %(timestamp)s, %(team_id)s, %(distinct_id)s, %(elements_chain)s, %(created_at)s, now(), 0
"""

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
SELECT DISTINCT trim(BOTH '\"' FROM JSONExtractRaw(properties, %(key)s)) FROM events where JSONHas(properties, %(key)s) AND team_id = %(team_id)s {parsed_date_from} {parsed_date_to} LIMIT 10
"""

SELECT_PROP_VALUES_SQL_WITH_FILTER = """
SELECT DISTINCT trim(BOTH '\"' FROM JSONExtractRaw(properties, %(key)s)) FROM events where team_id = %(team_id)s AND trim(BOTH '\"' FROM JSONExtractRaw(properties, %(key)s)) LIKE %(value)s {parsed_date_from} {parsed_date_to} LIMIT 10
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
ORDER BY toDate(timestamp) {order}, timestamp {order} {limit}
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
ORDER BY toDate(timestamp) {order}, timestamp {order} {limit}
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

GET_EARLIEST_TIMESTAMP_SQL = """
SELECT timestamp from events WHERE team_id = %(team_id)s order by toDate(timestamp), timestamp limit 1
"""

NULL_SQL = """
-- Creates zero values for all date axis ticks for the given date_from, date_to range
SELECT toUInt16(0) AS total, {trunc_func}(toDateTime(%(date_to)s) - {interval_func}(number)) AS day_start

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
FROM numbers(dateDiff(%(interval)s, toDateTime(%(date_from)s), toDateTime(%(date_to)s)))

UNION ALL

-- Make sure we capture the interval date_from falls into.
SELECT toUInt16(0) AS total, {trunc_func}(toDateTime(%(date_from)s))
"""

EVENT_JOIN_PERSON_SQL = f"""
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
    tag_regex=EXTRACT_TAG_REGEX, text_regex=EXTRACT_TEXT_REGEX
)

GET_CUSTOM_EVENTS = """
SELECT DISTINCT event FROM events where team_id = %(team_id)s AND event NOT IN ['$autocapture', '$pageview', '$identify', '$pageleave', '$screen']
"""

GET_EVENTS_VOLUME = "SELECT event, count(1) as count FROM events WHERE team_id = %(team_id)s AND timestamp > %(timestamp)s GROUP BY event ORDER BY count DESC"
