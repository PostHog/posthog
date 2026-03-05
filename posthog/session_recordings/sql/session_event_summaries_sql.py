from django.conf import settings

from posthog.clickhouse.kafka_engine import ttl_period
from posthog.clickhouse.table_engines import AggregatingMergeTree, Distributed, ReplicationScheme

TABLE_BASE_NAME = "session_event_summaries"
DATA_TABLE_NAME = f"sharded_{TABLE_BASE_NAME}"
WRITABLE_TABLE_NAME = f"writable_{TABLE_BASE_NAME}"
MV_NAME = f"{TABLE_BASE_NAME}_mv"

TTL_DAYS = 90


def SESSION_EVENT_SUMMARIES_DATA_TABLE_ENGINE():
    return AggregatingMergeTree(TABLE_BASE_NAME, replication_scheme=ReplicationScheme.SHARDED)


SESSION_EVENT_SUMMARIES_TABLE_BASE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name}
(
    team_id Int64,
    session_id String,
    event LowCardinality(String),
    event_count SimpleAggregateFunction(sum, Int64),
    distinct_hosts SimpleAggregateFunction(groupUniqArrayArray, Array(String)),
    distinct_emails SimpleAggregateFunction(groupUniqArrayArray, Array(String)),
    min_timestamp SimpleAggregateFunction(min, DateTime64(6, 'UTC')),
    max_timestamp SimpleAggregateFunction(max, DateTime64(6, 'UTC')),
    _timestamp SimpleAggregateFunction(max, DateTime)
) ENGINE = {engine}
"""


def SESSION_EVENT_SUMMARIES_DATA_TABLE_SQL():
    return (
        SESSION_EVENT_SUMMARIES_TABLE_BASE_SQL
        + """
PARTITION BY toYYYYMM(min_timestamp)
ORDER BY (team_id, event, session_id)
{ttl}
SETTINGS index_granularity=512
"""
    ).format(
        table_name=DATA_TABLE_NAME,
        engine=SESSION_EVENT_SUMMARIES_DATA_TABLE_ENGINE(),
        ttl=ttl_period("min_timestamp", TTL_DAYS, "DAY"),
    )


def WRITABLE_SESSION_EVENT_SUMMARIES_TABLE_SQL():
    return SESSION_EVENT_SUMMARIES_TABLE_BASE_SQL.format(
        table_name=WRITABLE_TABLE_NAME,
        engine=Distributed(
            data_table=DATA_TABLE_NAME,
            sharding_key="sipHash64(session_id)",
        ),
    )


def DISTRIBUTED_SESSION_EVENT_SUMMARIES_TABLE_SQL():
    return SESSION_EVENT_SUMMARIES_TABLE_BASE_SQL.format(
        table_name=TABLE_BASE_NAME,
        engine=Distributed(
            data_table=DATA_TABLE_NAME,
            sharding_key="sipHash64(session_id)",
        ),
    )


def SESSION_EVENT_SUMMARIES_MV_SQL():
    return """
CREATE MATERIALIZED VIEW IF NOT EXISTS {mv_name}
TO {database}.{target_table}
AS SELECT
    team_id,
    JSONExtractString(properties, '$session_id') as session_id,
    event,
    toInt64(count()) as event_count,
    groupUniqArrayIf(JSONExtractString(properties, '$host'), notEmpty(JSONExtractString(properties, '$host'))) as distinct_hosts,
    groupUniqArrayIf(JSONExtractString(person_properties, 'email'), notEmpty(JSONExtractString(person_properties, 'email'))) as distinct_emails,
    min(timestamp) as min_timestamp,
    max(timestamp) as max_timestamp,
    max(_timestamp) as _timestamp
FROM {database}.kafka_events_json
WHERE length(JSONExtractString(properties, '$session_id')) > 0
GROUP BY team_id, session_id, event
""".format(
        mv_name=MV_NAME,
        target_table=WRITABLE_TABLE_NAME,
        database=settings.CLICKHOUSE_DATABASE,
    )


def DROP_SESSION_EVENT_SUMMARIES_TABLE_SQL():
    return f"DROP TABLE IF EXISTS {DATA_TABLE_NAME}"


def DROP_SESSION_EVENT_SUMMARIES_MV_SQL():
    return f"DROP TABLE IF EXISTS {MV_NAME}"


def TRUNCATE_SESSION_EVENT_SUMMARIES_TABLE_SQL():
    return f"TRUNCATE TABLE IF EXISTS {DATA_TABLE_NAME}"
