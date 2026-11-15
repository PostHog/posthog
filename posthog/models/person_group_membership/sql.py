from django.conf import settings

from posthog.hogql.escape_sql import escape_clickhouse_identifier, escape_clickhouse_string

from posthog.clickhouse.client.connection import ClickHouseUser, get_clickhouse_creds
from posthog.clickhouse.kafka_engine import (
    CONSUMER_GROUP_PERSON_GROUP_MEMBERSHIP,
    kafka_engine,
    kafka_num_consumers,
    trim_quotes_expr,
)
from posthog.clickhouse.table_engines import AggregatingMergeTree, Distributed, ReplacingMergeTree, ReplicationScheme
from posthog.kafka_client.topics import KAFKA_EVENTS_JSON

PERSON_GROUP_MEMBERSHIP_TABLE = "person_group_membership"
SHARDED_PERSON_GROUP_MEMBERSHIP_TABLE = f"sharded_{PERSON_GROUP_MEMBERSHIP_TABLE}"
WRITABLE_PERSON_GROUP_MEMBERSHIP_TABLE = f"writable_{PERSON_GROUP_MEMBERSHIP_TABLE}"
KAFKA_PERSON_GROUP_MEMBERSHIP_TABLE = f"kafka_{PERSON_GROUP_MEMBERSHIP_TABLE}"
PERSON_GROUP_MEMBERSHIP_MV = f"{PERSON_GROUP_MEMBERSHIP_TABLE}_mv"

PERSON_GROUP_MEMBERSHIP_CONFIG_TABLE = "person_group_membership_config"
DISTRIBUTED_PERSON_GROUP_MEMBERSHIP_CONFIG_TABLE = f"distributed_{PERSON_GROUP_MEMBERSHIP_CONFIG_TABLE}"
PERSON_GROUP_MEMBERSHIP_CONFIG_DICTIONARY = f"{PERSON_GROUP_MEMBERSHIP_CONFIG_TABLE}_dict"

PERSON_GROUP_MEMBERSHIP_MAX_GROUP_TYPE_INDEX = 4
PERSON_GROUP_MEMBERSHIP_CONFIG_DICTIONARY_LIFETIME_MAX_SECONDS = 120
PERSON_GROUP_MEMBERSHIP_CONFIG_DICTIONARY_DEFAULT_GROUP_TYPE_INDEX = 255

PERSON_GROUP_MEMBERSHIP_COLUMNS = """
    team_id Int64,
    group_type_index UInt8,
    group_key String,
    distinct_id String,
    first_seen SimpleAggregateFunction(min, DateTime64(6, 'UTC')),
    last_seen SimpleAggregateFunction(max, DateTime64(6, 'UTC'))
""".strip()

KAFKA_PERSON_GROUP_MEMBERSHIP_COLUMNS = """
    team_id Int64,
    distinct_id String,
    properties String,
    timestamp DateTime64(6, 'UTC'),
    person_mode Enum8('full' = 0, 'propertyless' = 1, 'force_upgrade' = 2)
""".strip()

PERSON_GROUP_MEMBERSHIP_CONFIG_COLUMNS = """
    team_id Int64,
    group_type_index UInt8,
    enabled UInt8,
    version UInt64
""".strip()


def SHARDED_PERSON_GROUP_MEMBERSHIP_TABLE_SQL() -> str:
    # Wide parts let lightweight deletes rewrite the row mask without rewriting membership columns.
    # The distinct_id index serves person lookups and person deletion, which the sort key cannot narrow.
    return f"""
CREATE TABLE IF NOT EXISTS {SHARDED_PERSON_GROUP_MEMBERSHIP_TABLE}
(
    {PERSON_GROUP_MEMBERSHIP_COLUMNS},
    INDEX idx_distinct_id distinct_id TYPE bloom_filter(0.01) GRANULARITY 1
)
ENGINE = {AggregatingMergeTree(SHARDED_PERSON_GROUP_MEMBERSHIP_TABLE, replication_scheme=ReplicationScheme.SHARDED)}
ORDER BY (team_id, group_type_index, group_key, distinct_id)
SETTINGS index_granularity = 8192, min_rows_for_wide_part = 0, min_bytes_for_wide_part = 0
"""


def DISTRIBUTED_PERSON_GROUP_MEMBERSHIP_TABLE_SQL() -> str:
    return f"""
CREATE TABLE IF NOT EXISTS {PERSON_GROUP_MEMBERSHIP_TABLE}
(
    {PERSON_GROUP_MEMBERSHIP_COLUMNS}
)
ENGINE = {
        Distributed(
            data_table=SHARDED_PERSON_GROUP_MEMBERSHIP_TABLE,
            sharding_key="sipHash64(team_id, group_type_index, group_key)",
            cluster=settings.CLICKHOUSE_AUX_CLUSTER,
        )
    }
"""


def WRITABLE_PERSON_GROUP_MEMBERSHIP_TABLE_SQL() -> str:
    return f"""
CREATE TABLE IF NOT EXISTS {WRITABLE_PERSON_GROUP_MEMBERSHIP_TABLE}
(
    {PERSON_GROUP_MEMBERSHIP_COLUMNS}
)
ENGINE = {
        Distributed(
            data_table=SHARDED_PERSON_GROUP_MEMBERSHIP_TABLE,
            sharding_key="sipHash64(team_id, group_type_index, group_key)",
            cluster=settings.CLICKHOUSE_AUX_CLUSTER,
        )
    }
"""


def PERSON_GROUP_MEMBERSHIP_CONFIG_TABLE_SQL() -> str:
    return f"""
CREATE TABLE IF NOT EXISTS {PERSON_GROUP_MEMBERSHIP_CONFIG_TABLE}
(
    {PERSON_GROUP_MEMBERSHIP_CONFIG_COLUMNS}
)
ENGINE = {ReplacingMergeTree(PERSON_GROUP_MEMBERSHIP_CONFIG_TABLE, ver="version")}
ORDER BY team_id
SETTINGS index_granularity = 8192
"""


def DISTRIBUTED_PERSON_GROUP_MEMBERSHIP_CONFIG_TABLE_SQL() -> str:
    return f"""
CREATE TABLE IF NOT EXISTS {DISTRIBUTED_PERSON_GROUP_MEMBERSHIP_CONFIG_TABLE}
(
    {PERSON_GROUP_MEMBERSHIP_CONFIG_COLUMNS}
)
ENGINE = {
        Distributed(
            data_table=PERSON_GROUP_MEMBERSHIP_CONFIG_TABLE,
            sharding_key="sipHash64(team_id)",
            cluster=settings.CLICKHOUSE_AUX_CLUSTER,
        )
    }
"""


def PERSON_GROUP_MEMBERSHIP_CONFIG_DICTIONARY_SQL() -> str:
    database = escape_clickhouse_identifier(settings.CLICKHOUSE_DATABASE)
    creds = get_clickhouse_creds(ClickHouseUser.DICT_READER)
    # Filter after argMax so a newer disabled or invalid row cannot revive an older valid config.
    query = (
        "SELECT team_id, config.1 AS group_type_index, config.2 AS enabled "
        "FROM (SELECT team_id, argMax(tuple(group_type_index, enabled), version) AS config "
        f"FROM {database}.{DISTRIBUTED_PERSON_GROUP_MEMBERSHIP_CONFIG_TABLE} GROUP BY team_id) "
        f"WHERE enabled = 1 AND group_type_index <= {PERSON_GROUP_MEMBERSHIP_MAX_GROUP_TYPE_INDEX}"
    )
    source = f"QUERY {escape_clickhouse_string(query)} USER {escape_clickhouse_string(creds.user)}"
    if creds.password:
        source += f" PASSWORD {escape_clickhouse_string(creds.password)}"
    return f"""
CREATE DICTIONARY IF NOT EXISTS {PERSON_GROUP_MEMBERSHIP_CONFIG_DICTIONARY}
(
    team_id Int64,
    group_type_index UInt8 DEFAULT {PERSON_GROUP_MEMBERSHIP_CONFIG_DICTIONARY_DEFAULT_GROUP_TYPE_INDEX},
    enabled UInt8 DEFAULT 0
)
PRIMARY KEY team_id
SOURCE(CLICKHOUSE({source}))
LIFETIME(MIN 60 MAX {PERSON_GROUP_MEMBERSHIP_CONFIG_DICTIONARY_LIFETIME_MAX_SECONDS})
LAYOUT(COMPLEX_KEY_HASHED())
"""


def KAFKA_PERSON_GROUP_MEMBERSHIP_TABLE_SQL() -> str:
    # A dedicated consumer group keeps membership lag and failures off the main events consumer.
    # Each row carries the full properties JSON, so blocks stay at the flag_evaluations sizes.
    return f"""
CREATE TABLE IF NOT EXISTS {KAFKA_PERSON_GROUP_MEMBERSHIP_TABLE}
(
    {KAFKA_PERSON_GROUP_MEMBERSHIP_COLUMNS}
)
ENGINE = {
        kafka_engine(
            topic=KAFKA_EVENTS_JSON,
            group=CONSUMER_GROUP_PERSON_GROUP_MEMBERSHIP,
            named_collection=settings.CLICKHOUSE_KAFKA_WARPSTREAM_INGESTION_NAMED_COLLECTION,
        )
    }
SETTINGS
    kafka_max_block_size = 10000,
    kafka_poll_max_batch_size = 10000,
    kafka_poll_timeout_ms = 10000,
    kafka_flush_interval_ms = 7500,
    kafka_num_consumers = {kafka_num_consumers(1)},
    kafka_thread_per_consumer = 1,
    kafka_skip_broken_messages = 100
"""


# Matches the events $group_N columns the backfill reads, so numeric keys become strings in both paths.
GROUP_KEY_EXPR = trim_quotes_expr("JSONExtractRaw(properties, concat('$group_', toString(group_type_index)))")


def PERSON_GROUP_MEMBERSHIP_MV_SELECT_SQL(source_table: str) -> str:
    # Filter on the dictionary before extracting the group key, so ineligible events skip JSON parsing.
    # The dictionary holds only enabled, valid configs, so dictHas fails closed for every other team.
    # dictHas also avoids the inverse dictionary lookup rewrite, which rejects dictGet comparisons on complex keys.
    # Personless events cannot be backed by a person profile. The read path keeps identified persons only.
    dictionary = f"{settings.CLICKHOUSE_DATABASE}.{PERSON_GROUP_MEMBERSHIP_CONFIG_DICTIONARY}"
    return f"""SELECT
    team_id,
    group_type_index,
    {GROUP_KEY_EXPR} AS group_key,
    distinct_id,
    min(timestamp) AS first_seen,
    max(timestamp) AS last_seen
FROM (
    SELECT
        team_id,
        dictGet('{dictionary}', 'group_type_index', tuple(team_id)) AS group_type_index,
        distinct_id,
        properties,
        timestamp
    FROM {source_table}
    WHERE dictHas('{dictionary}', tuple(team_id)) AND (person_mode != 'propertyless')
      AND JSONExtractRaw(properties, '$update_person_last_seen_at') != 'false'
)
WHERE notEmpty(group_key)
GROUP BY team_id, group_type_index, group_key, distinct_id"""


def PERSON_GROUP_MEMBERSHIP_MV_SQL() -> str:
    return f"""
CREATE MATERIALIZED VIEW IF NOT EXISTS {PERSON_GROUP_MEMBERSHIP_MV}
TO {WRITABLE_PERSON_GROUP_MEMBERSHIP_TABLE}
AS {PERSON_GROUP_MEMBERSHIP_MV_SELECT_SQL(KAFKA_PERSON_GROUP_MEMBERSHIP_TABLE)}
"""
