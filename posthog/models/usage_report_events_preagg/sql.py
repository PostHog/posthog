from django.conf import settings

from posthog.clickhouse.kafka_engine import kafka_engine, trim_quotes_expr
from posthog.clickhouse.table_engines import AggregatingMergeTree, Distributed, ReplacingMergeTree, ReplicationScheme
from posthog.kafka_client.topics import KAFKA_EVENTS_JSON

LEGACY_USAGE_REPORT_EVENTS_PREAGG_TABLE = "usage_report_events_preagg"
LEGACY_SHARDED_USAGE_REPORT_EVENTS_PREAGG_TABLE = f"sharded_{LEGACY_USAGE_REPORT_EVENTS_PREAGG_TABLE}"
LEGACY_WRITABLE_USAGE_REPORT_EVENTS_PREAGG_TABLE = f"writable_{LEGACY_USAGE_REPORT_EVENTS_PREAGG_TABLE}"
LEGACY_USAGE_REPORT_EVENTS_PREAGG_MV = f"{LEGACY_USAGE_REPORT_EVENTS_PREAGG_TABLE}_mv"
LEGACY_KAFKA_USAGE_REPORT_EVENTS_PREAGG_TABLE = f"kafka_{LEGACY_USAGE_REPORT_EVENTS_PREAGG_TABLE}"

# Keep this string local to the legacy SQL helpers so historical migrations can
# still render without keeping a live Kafka consumer-group constant around.
_LEGACY_CONSUMER_GROUP_USAGE_REPORT_EVENTS_PREAGG = "clickhouse_usage_report_events_preagg"

USAGE_REPORT_EVENTS_COUNT_PREAGGREGATED_TABLE = "usage_report_events_count_preaggregated"
SHARDED_USAGE_REPORT_EVENTS_COUNT_PREAGGREGATED_TABLE = f"sharded_{USAGE_REPORT_EVENTS_COUNT_PREAGGREGATED_TABLE}"

USAGE_REPORT_EVENTS_DEDUP_PREAGGREGATED_TABLE = "usage_report_events_dedup_preaggregated"
SHARDED_USAGE_REPORT_EVENTS_DEDUP_PREAGGREGATED_TABLE = f"sharded_{USAGE_REPORT_EVENTS_DEDUP_PREAGGREGATED_TABLE}"

USAGE_REPORT_EVENTS_PREAGGREGATION_WATERMARKS_TABLE = "usage_report_events_preaggregation_watermarks"
SHARDED_USAGE_REPORT_EVENTS_PREAGGREGATION_WATERMARKS_TABLE = (
    f"sharded_{USAGE_REPORT_EVENTS_PREAGGREGATION_WATERMARKS_TABLE}"
)

USAGE_REPORT_EVENTS_PREAGG_TTL_DAYS = 14
USAGE_REPORT_EVENTS_PREAGG_BUCKET_MINUTES = 15


def _event_property_string_expression(property_name: str) -> str:
    return trim_quotes_expr(f"JSONExtractRaw(properties, '{property_name}')")


USAGE_REPORT_EVENTS_LIB_EXPRESSION = _event_property_string_expression("$lib")
USAGE_REPORT_EVENTS_HAS_GROUP_EXPRESSION = " OR ".join(
    f"{_event_property_string_expression(f'$group_{index}')} != ''" for index in range(5)
)


USAGE_REPORT_EVENTS_COUNT_PREAGGREGATED_COLUMNS = """
    date Date,
    bucket_start DateTime64(6, 'UTC'),
    team_id Int64,
    person_mode LowCardinality(String),
    lib LowCardinality(String),
    event String,
    has_group UInt8,
    event_count UInt64,
    computed_at DateTime64(6, 'UTC') DEFAULT now()
""".strip()


USAGE_REPORT_EVENTS_DEDUP_PREAGGREGATED_COLUMNS = """
    date Date,
    bucket_start DateTime64(6, 'UTC'),
    team_id Int64,
    usage_kind LowCardinality(String),
    event String,
    raw_count UInt64,
    computed_at DateTime64(6, 'UTC') DEFAULT now()
""".strip()


USAGE_REPORT_EVENTS_PREAGGREGATION_WATERMARKS_COLUMNS = """
    bucket_start DateTime64(6, 'UTC'),
    bucket_end DateTime64(6, 'UTC'),
    computed_at DateTime64(6, 'UTC') DEFAULT now()
""".strip()


def SHARDED_USAGE_REPORT_EVENTS_COUNT_PREAGGREGATED_TABLE_ENGINE() -> ReplacingMergeTree:
    return ReplacingMergeTree(
        USAGE_REPORT_EVENTS_COUNT_PREAGGREGATED_TABLE,
        replication_scheme=ReplicationScheme.SHARDED,
        ver="computed_at",
    )


def SHARDED_USAGE_REPORT_EVENTS_DEDUP_PREAGGREGATED_TABLE_ENGINE() -> ReplacingMergeTree:
    return ReplacingMergeTree(
        USAGE_REPORT_EVENTS_DEDUP_PREAGGREGATED_TABLE,
        replication_scheme=ReplicationScheme.SHARDED,
        ver="computed_at",
    )


def SHARDED_USAGE_REPORT_EVENTS_PREAGGREGATION_WATERMARKS_TABLE_ENGINE() -> ReplacingMergeTree:
    return ReplacingMergeTree(
        USAGE_REPORT_EVENTS_PREAGGREGATION_WATERMARKS_TABLE,
        replication_scheme=ReplicationScheme.SHARDED,
        ver="computed_at",
    )


def SHARDED_USAGE_REPORT_EVENTS_COUNT_PREAGGREGATED_TABLE_SQL() -> str:
    return f"""
CREATE TABLE IF NOT EXISTS {SHARDED_USAGE_REPORT_EVENTS_COUNT_PREAGGREGATED_TABLE}
(
    {USAGE_REPORT_EVENTS_COUNT_PREAGGREGATED_COLUMNS}
)
ENGINE = {SHARDED_USAGE_REPORT_EVENTS_COUNT_PREAGGREGATED_TABLE_ENGINE()}
PARTITION BY date
ORDER BY (date, team_id, bucket_start, person_mode, lib, event, has_group)
TTL date + INTERVAL {USAGE_REPORT_EVENTS_PREAGG_TTL_DAYS} DAY
SETTINGS ttl_only_drop_parts = 1
"""


def DISTRIBUTED_USAGE_REPORT_EVENTS_COUNT_PREAGGREGATED_TABLE_SQL() -> str:
    return f"""
CREATE TABLE IF NOT EXISTS {USAGE_REPORT_EVENTS_COUNT_PREAGGREGATED_TABLE}
(
    {USAGE_REPORT_EVENTS_COUNT_PREAGGREGATED_COLUMNS}
)
ENGINE = {
        Distributed(
            data_table=SHARDED_USAGE_REPORT_EVENTS_COUNT_PREAGGREGATED_TABLE,
            sharding_key="sipHash64(team_id, date, bucket_start, event)",
            cluster=settings.CLICKHOUSE_AUX_CLUSTER,
        )
    }
"""


def SHARDED_USAGE_REPORT_EVENTS_DEDUP_PREAGGREGATED_TABLE_SQL() -> str:
    return f"""
CREATE TABLE IF NOT EXISTS {SHARDED_USAGE_REPORT_EVENTS_DEDUP_PREAGGREGATED_TABLE}
(
    {USAGE_REPORT_EVENTS_DEDUP_PREAGGREGATED_COLUMNS}
)
ENGINE = {SHARDED_USAGE_REPORT_EVENTS_DEDUP_PREAGGREGATED_TABLE_ENGINE()}
PARTITION BY date
ORDER BY (date, team_id, bucket_start, usage_kind, event)
TTL date + INTERVAL {USAGE_REPORT_EVENTS_PREAGG_TTL_DAYS} DAY
SETTINGS ttl_only_drop_parts = 1
"""


def DISTRIBUTED_USAGE_REPORT_EVENTS_DEDUP_PREAGGREGATED_TABLE_SQL() -> str:
    return f"""
CREATE TABLE IF NOT EXISTS {USAGE_REPORT_EVENTS_DEDUP_PREAGGREGATED_TABLE}
(
    {USAGE_REPORT_EVENTS_DEDUP_PREAGGREGATED_COLUMNS}
)
ENGINE = {
        Distributed(
            data_table=SHARDED_USAGE_REPORT_EVENTS_DEDUP_PREAGGREGATED_TABLE,
            sharding_key="sipHash64(team_id, date, bucket_start, event)",
            cluster=settings.CLICKHOUSE_AUX_CLUSTER,
        )
    }
"""


def SHARDED_USAGE_REPORT_EVENTS_PREAGGREGATION_WATERMARKS_TABLE_SQL() -> str:
    return f"""
CREATE TABLE IF NOT EXISTS {SHARDED_USAGE_REPORT_EVENTS_PREAGGREGATION_WATERMARKS_TABLE}
(
    {USAGE_REPORT_EVENTS_PREAGGREGATION_WATERMARKS_COLUMNS}
)
ENGINE = {SHARDED_USAGE_REPORT_EVENTS_PREAGGREGATION_WATERMARKS_TABLE_ENGINE()}
PARTITION BY toDate(bucket_start)
ORDER BY bucket_start
TTL toDate(bucket_start) + INTERVAL {USAGE_REPORT_EVENTS_PREAGG_TTL_DAYS} DAY
SETTINGS ttl_only_drop_parts = 1
"""


def DISTRIBUTED_USAGE_REPORT_EVENTS_PREAGGREGATION_WATERMARKS_TABLE_SQL() -> str:
    return f"""
CREATE TABLE IF NOT EXISTS {USAGE_REPORT_EVENTS_PREAGGREGATION_WATERMARKS_TABLE}
(
    {USAGE_REPORT_EVENTS_PREAGGREGATION_WATERMARKS_COLUMNS}
)
ENGINE = {
        Distributed(
            data_table=SHARDED_USAGE_REPORT_EVENTS_PREAGGREGATION_WATERMARKS_TABLE,
            sharding_key="sipHash64(bucket_start)",
            cluster=settings.CLICKHOUSE_AUX_CLUSTER,
        )
    }
"""


def DROP_LEGACY_USAGE_REPORT_EVENTS_PREAGG_MV_SQL() -> str:
    return f"DROP TABLE IF EXISTS {LEGACY_USAGE_REPORT_EVENTS_PREAGG_MV}"


def DROP_LEGACY_KAFKA_USAGE_REPORT_EVENTS_PREAGG_TABLE_SQL() -> str:
    return f"DROP TABLE IF EXISTS {LEGACY_KAFKA_USAGE_REPORT_EVENTS_PREAGG_TABLE}"


def DROP_LEGACY_WRITABLE_USAGE_REPORT_EVENTS_PREAGG_TABLE_SQL() -> str:
    return f"DROP TABLE IF EXISTS {LEGACY_WRITABLE_USAGE_REPORT_EVENTS_PREAGG_TABLE}"


def DROP_LEGACY_DISTRIBUTED_USAGE_REPORT_EVENTS_PREAGG_TABLE_SQL() -> str:
    return f"DROP TABLE IF EXISTS {LEGACY_USAGE_REPORT_EVENTS_PREAGG_TABLE}"


def DROP_LEGACY_SHARDED_USAGE_REPORT_EVENTS_PREAGG_TABLE_SQL() -> str:
    return f"DROP TABLE IF EXISTS {LEGACY_SHARDED_USAGE_REPORT_EVENTS_PREAGG_TABLE} SYNC"


def INSERT_USAGE_REPORT_EVENTS_COUNT_PREAGGREGATED_SQL() -> str:
    return f"""
INSERT INTO {USAGE_REPORT_EVENTS_COUNT_PREAGGREGATED_TABLE}
    (date, bucket_start, team_id, person_mode, lib, event, has_group, event_count, computed_at)
SELECT
    toDate(timestamp) AS date,
    toStartOfInterval(inserted_at, INTERVAL {USAGE_REPORT_EVENTS_PREAGG_BUCKET_MINUTES} MINUTE) AS bucket_start,
    team_id,
    toString(person_mode) AS person_mode,
    {USAGE_REPORT_EVENTS_LIB_EXPRESSION} AS lib,
    event,
    toUInt8({USAGE_REPORT_EVENTS_HAS_GROUP_EXPRESSION}) AS has_group,
    count() AS event_count,
    %(computed_at)s AS computed_at
FROM events_recent
WHERE inserted_at >= %(bucket_start)s
  AND inserted_at < %(bucket_end)s
GROUP BY date, bucket_start, team_id, person_mode, lib, event, has_group
"""


def INSERT_USAGE_REPORT_EVENTS_DEDUP_PREAGGREGATED_SQL() -> str:
    return f"""
INSERT INTO {USAGE_REPORT_EVENTS_DEDUP_PREAGGREGATED_TABLE}
    (date, bucket_start, team_id, usage_kind, event, raw_count, computed_at)
SELECT
    date,
    bucket_start,
    team_id,
    usage_kind,
    event,
    raw_count,
    computed_at
FROM
(
    SELECT
        toDate(timestamp) AS date,
        toStartOfInterval(inserted_at, INTERVAL {USAGE_REPORT_EVENTS_PREAGG_BUCKET_MINUTES} MINUTE) AS bucket_start,
        team_id,
        'all' AS usage_kind,
        event,
        count() AS raw_count,
        %(computed_at)s AS computed_at
    FROM events_recent
    WHERE inserted_at >= %(bucket_start)s
      AND inserted_at < %(bucket_end)s
    GROUP BY date, bucket_start, team_id, usage_kind, event

    UNION ALL

    SELECT
        toDate(timestamp) AS date,
        toStartOfInterval(inserted_at, INTERVAL {USAGE_REPORT_EVENTS_PREAGG_BUCKET_MINUTES} MINUTE) AS bucket_start,
        team_id,
        'enhanced_persons' AS usage_kind,
        event,
        count() AS raw_count,
        %(computed_at)s AS computed_at
    FROM events_recent
    WHERE inserted_at >= %(bucket_start)s
      AND inserted_at < %(bucket_end)s
      AND person_mode IN ('full', 'force_upgrade')
    GROUP BY date, bucket_start, team_id, usage_kind, event
)
"""


def INSERT_USAGE_REPORT_EVENTS_PREAGGREGATION_WATERMARK_SQL() -> str:
    return f"""
INSERT INTO {USAGE_REPORT_EVENTS_PREAGGREGATION_WATERMARKS_TABLE}
    (bucket_start, bucket_end, computed_at)
SELECT
    %(bucket_start)s AS bucket_start,
    %(bucket_end)s AS bucket_end,
    %(computed_at)s AS computed_at
"""


def USAGE_REPORT_EVENTS_PREAGGREGATION_BOUNDS_SQL() -> str:
    return f"""
WITH
    toStartOfInterval(toDateTime64(%(begin)s, 6, 'UTC'), INTERVAL {USAGE_REPORT_EVENTS_PREAGG_BUCKET_MINUTES} MINUTE) AS requested_begin,
    toStartOfInterval(toDateTime64(%(end)s, 6, 'UTC'), INTERVAL {USAGE_REPORT_EVENTS_PREAGG_BUCKET_MINUTES} MINUTE) AS requested_end
SELECT min(bucket_start) AS min_bucket_start, max(bucket_end) AS max_bucket_end
FROM
(
    SELECT
        bucket_start,
        bucket_end
    FROM
    (
        SELECT
            bucket_start,
            bucket_end,
            row_number() OVER (ORDER BY bucket_start) - 1 AS bucket_index,
            intDiv(dateDiff('minute', requested_begin, bucket_start), {USAGE_REPORT_EVENTS_PREAGG_BUCKET_MINUTES}) AS expected_bucket_index
        FROM
        (
            SELECT
                bucket_start,
                argMax(bucket_end, computed_at) AS bucket_end
            FROM {USAGE_REPORT_EVENTS_PREAGGREGATION_WATERMARKS_TABLE}
            WHERE bucket_start >= requested_begin
              AND bucket_start < requested_end
            GROUP BY bucket_start
        )
    )
    WHERE bucket_index = expected_bucket_index
)
"""


def USAGE_REPORT_EVENTS_LATEST_BUCKET_VERSIONS_CTE_SQL() -> str:
    return f"""
latest_bucket_versions AS
(
    SELECT
        bucket_start,
        max(computed_at) AS computed_at
    FROM {USAGE_REPORT_EVENTS_PREAGGREGATION_WATERMARKS_TABLE}
    WHERE bucket_start < %(max_bucket_end)s
    GROUP BY bucket_start
)
""".strip()


def USAGE_REPORT_EVENTS_DEDUP_PREAGGREGATED_READ_SQL(count_column: str) -> str:
    if count_column != "raw_count":
        raise ValueError(f"Unsupported usage report events preaggregation count column: {count_column}")

    return f"""
WITH {USAGE_REPORT_EVENTS_LATEST_BUCKET_VERSIONS_CTE_SQL()}
SELECT team_id, sum(count) AS count
FROM
(
    SELECT
        d.date,
        d.bucket_start,
        d.team_id,
        d.usage_kind,
        d.event,
        max(d.{count_column}) AS count
    FROM {USAGE_REPORT_EVENTS_DEDUP_PREAGGREGATED_TABLE} d
    INNER JOIN latest_bucket_versions
        ON d.bucket_start = latest_bucket_versions.bucket_start
       AND d.computed_at = latest_bucket_versions.computed_at
    WHERE d.date >= toDate(%(begin)s)
      AND d.date < toDate(%(end)s)
      AND d.bucket_start < %(max_bucket_end)s
      AND d.usage_kind = %(usage_kind)s
      AND d.event NOT IN %(excluded_events)s
    GROUP BY d.date, d.bucket_start, d.team_id, d.usage_kind, d.event
)
GROUP BY team_id
"""


# Legacy helpers kept for historical migration 0251. New code must not use
# these tables: migration 0271 drops them and creates the scheduled tables.
USAGE_REPORT_EVENTS_PREAGG_TABLE = LEGACY_USAGE_REPORT_EVENTS_PREAGG_TABLE
SHARDED_USAGE_REPORT_EVENTS_PREAGG_TABLE = LEGACY_SHARDED_USAGE_REPORT_EVENTS_PREAGG_TABLE
WRITABLE_USAGE_REPORT_EVENTS_PREAGG_TABLE = LEGACY_WRITABLE_USAGE_REPORT_EVENTS_PREAGG_TABLE
USAGE_REPORT_EVENTS_PREAGG_MV = LEGACY_USAGE_REPORT_EVENTS_PREAGG_MV
KAFKA_USAGE_REPORT_EVENTS_PREAGG_TABLE = LEGACY_KAFKA_USAGE_REPORT_EVENTS_PREAGG_TABLE

USAGE_REPORT_EVENTS_PREAGG_COLUMNS = """
    date Date,
    team_id Int64,
    person_mode LowCardinality(String),
    lib LowCardinality(String),
    event String,
    distinct_events_unique AggregateFunction(uniqExact, Tuple(UInt64, UInt64, UInt64)),
    event_count AggregateFunction(sum, UInt64)
""".strip()

_KAFKA_USAGE_REPORT_EVENTS_PREAGG_COLUMNS = """
    uuid UUID,
    event VARCHAR,
    properties VARCHAR CODEC(ZSTD(3)),
    timestamp DateTime64(6, 'UTC'),
    team_id Int64,
    distinct_id VARCHAR,
    person_mode Enum8('full' = 0, 'propertyless' = 1, 'force_upgrade' = 2)
""".strip()


def SHARDED_USAGE_REPORT_EVENTS_PREAGG_TABLE_SQL() -> str:
    return f"""
CREATE TABLE IF NOT EXISTS {LEGACY_SHARDED_USAGE_REPORT_EVENTS_PREAGG_TABLE}
(
    {USAGE_REPORT_EVENTS_PREAGG_COLUMNS}
)
ENGINE = {AggregatingMergeTree(LEGACY_SHARDED_USAGE_REPORT_EVENTS_PREAGG_TABLE, replication_scheme=ReplicationScheme.SHARDED)}
PARTITION BY date
ORDER BY (date, team_id, person_mode, lib, event)
TTL date + INTERVAL {USAGE_REPORT_EVENTS_PREAGG_TTL_DAYS} DAY
SETTINGS ttl_only_drop_parts = 1
"""


def DISTRIBUTED_USAGE_REPORT_EVENTS_PREAGG_TABLE_SQL() -> str:
    return f"""
CREATE TABLE IF NOT EXISTS {LEGACY_USAGE_REPORT_EVENTS_PREAGG_TABLE}
(
    {USAGE_REPORT_EVENTS_PREAGG_COLUMNS}
)
ENGINE = {
        Distributed(
            data_table=LEGACY_SHARDED_USAGE_REPORT_EVENTS_PREAGG_TABLE,
            sharding_key="sipHash64(date)",
            cluster=settings.CLICKHOUSE_AUX_CLUSTER,
        )
    }
"""


def WRITABLE_USAGE_REPORT_EVENTS_PREAGG_TABLE_SQL() -> str:
    return f"""
CREATE TABLE IF NOT EXISTS {LEGACY_WRITABLE_USAGE_REPORT_EVENTS_PREAGG_TABLE}
(
    {USAGE_REPORT_EVENTS_PREAGG_COLUMNS}
)
ENGINE = {
        Distributed(
            data_table=LEGACY_SHARDED_USAGE_REPORT_EVENTS_PREAGG_TABLE,
            sharding_key="sipHash64(date)",
            cluster=settings.CLICKHOUSE_AUX_CLUSTER,
        )
    }
"""


def KAFKA_USAGE_REPORT_EVENTS_PREAGG_TABLE_SQL() -> str:
    return f"""
CREATE TABLE IF NOT EXISTS {LEGACY_KAFKA_USAGE_REPORT_EVENTS_PREAGG_TABLE}
(
    {_KAFKA_USAGE_REPORT_EVENTS_PREAGG_COLUMNS}
)
ENGINE = {
        kafka_engine(
            topic=KAFKA_EVENTS_JSON,
            group=_LEGACY_CONSUMER_GROUP_USAGE_REPORT_EVENTS_PREAGG,
            named_collection=settings.CLICKHOUSE_KAFKA_WARPSTREAM_INGESTION_NAMED_COLLECTION,
        )
    }
SETTINGS kafka_skip_broken_messages = 100, kafka_thread_per_consumer = 1, kafka_num_consumers = 1
"""


def USAGE_REPORT_EVENTS_PREAGG_MV_SQL() -> str:
    return f"""
CREATE MATERIALIZED VIEW IF NOT EXISTS {LEGACY_USAGE_REPORT_EVENTS_PREAGG_MV}
TO {LEGACY_WRITABLE_USAGE_REPORT_EVENTS_PREAGG_TABLE}
AS SELECT
    toDate(timestamp) AS date,
    team_id,
    person_mode,
    JSONExtractString(properties, '$lib') AS lib,
    event,
    uniqExactState((cityHash64(distinct_id), cityHash64(toString(uuid)), cityHash64(event))) AS distinct_events_unique,
    sumState(toUInt64(1)) AS event_count
FROM {LEGACY_KAFKA_USAGE_REPORT_EVENTS_PREAGG_TABLE}
GROUP BY date, team_id, person_mode, lib, event
"""
