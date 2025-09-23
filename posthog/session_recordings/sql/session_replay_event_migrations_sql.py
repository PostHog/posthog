from django.conf import settings

from posthog.session_recordings.sql.session_replay_event_sql import SESSION_REPLAY_EVENTS_DATA_TABLE


def DROP_SESSION_REPLAY_EVENTS_TABLE_MV_SQL(on_cluster=True):
    return "DROP TABLE IF EXISTS session_replay_events_mv" + (
        f" ON CLUSTER {settings.CLICKHOUSE_CLUSTER}" if on_cluster else ""
    )


def DROP_KAFKA_SESSION_REPLAY_EVENTS_TABLE_SQL(on_cluster=True):
    return "DROP TABLE IF EXISTS kafka_session_replay_events" + (
        f" ON CLUSTER {settings.CLICKHOUSE_CLUSTER}" if on_cluster else ""
    )


# this alter command exists because existing installations
# need to have the columns added, the SESSION_REPLAY_EVENTS_TABLE_BASE_SQL string
# already add the columns
# so, for e.g. test set up has them
# Which means this is a no-op for new installations
ALTER_SESSION_REPLAY_ADD_CONSOLE_COLUMNS = """
    ALTER TABLE {table_name} on CLUSTER '{cluster}'
        ADD COLUMN IF NOT EXISTS console_log_count SimpleAggregateFunction(sum, Int64),
        ADD COLUMN IF NOT EXISTS console_warn_count SimpleAggregateFunction(sum, Int64),
        ADD COLUMN IF NOT EXISTS console_error_count SimpleAggregateFunction(sum, Int64)
"""


ADD_CONSOLE_COUNTS_DISTRIBUTED_SESSION_REPLAY_EVENTS_TABLE_SQL = (
    lambda: ALTER_SESSION_REPLAY_ADD_CONSOLE_COLUMNS.format(
        table_name="session_replay_events",
        cluster=settings.CLICKHOUSE_CLUSTER,
    )
)

ADD_CONSOLE_COUNTS_WRITABLE_SESSION_REPLAY_EVENTS_TABLE_SQL = lambda: ALTER_SESSION_REPLAY_ADD_CONSOLE_COLUMNS.format(
    table_name="writable_session_replay_events",
    cluster=settings.CLICKHOUSE_CLUSTER,
)

ADD_CONSOLE_COUNTS_SESSION_REPLAY_EVENTS_TABLE_SQL = lambda: ALTER_SESSION_REPLAY_ADD_CONSOLE_COLUMNS.format(
    table_name=SESSION_REPLAY_EVENTS_DATA_TABLE(),
    cluster=settings.CLICKHOUSE_CLUSTER,
)

# migration to add size column to the session replay table
ALTER_SESSION_REPLAY_ADD_SIZE_COLUMN = """
    ALTER TABLE {table_name} on CLUSTER '{cluster}'
        ADD COLUMN IF NOT EXISTS size SimpleAggregateFunction(sum, Int64)
"""


ADD_SIZE_DISTRIBUTED_SESSION_REPLAY_EVENTS_TABLE_SQL = lambda: ALTER_SESSION_REPLAY_ADD_SIZE_COLUMN.format(
    table_name="session_replay_events",
    cluster=settings.CLICKHOUSE_CLUSTER,
)

ADD_SIZE_WRITABLE_SESSION_REPLAY_EVENTS_TABLE_SQL = lambda: ALTER_SESSION_REPLAY_ADD_SIZE_COLUMN.format(
    table_name="writable_session_replay_events",
    cluster=settings.CLICKHOUSE_CLUSTER,
)

ADD_SIZE_SESSION_REPLAY_EVENTS_TABLE_SQL = lambda: ALTER_SESSION_REPLAY_ADD_SIZE_COLUMN.format(
    table_name=SESSION_REPLAY_EVENTS_DATA_TABLE(),
    cluster=settings.CLICKHOUSE_CLUSTER,
)

# migration to add size column to the session replay table
ALTER_SESSION_REPLAY_ADD_EVENT_COUNT_COLUMN = """
    ALTER TABLE {table_name} on CLUSTER '{cluster}'
        ADD COLUMN IF NOT EXISTS message_count SimpleAggregateFunction(sum, Int64),
        ADD COLUMN IF NOT EXISTS event_count SimpleAggregateFunction(sum, Int64),
        -- fly by addition so that we can track lag in the data the same way as for other tables
        ADD COLUMN IF NOT EXISTS _timestamp SimpleAggregateFunction(max, DateTime)
"""

ADD_EVENT_COUNT_DISTRIBUTED_SESSION_REPLAY_EVENTS_TABLE_SQL = (
    lambda: ALTER_SESSION_REPLAY_ADD_EVENT_COUNT_COLUMN.format(
        table_name="session_replay_events",
        cluster=settings.CLICKHOUSE_CLUSTER,
    )
)

ADD_EVENT_COUNT_WRITABLE_SESSION_REPLAY_EVENTS_TABLE_SQL = lambda: ALTER_SESSION_REPLAY_ADD_EVENT_COUNT_COLUMN.format(
    table_name="writable_session_replay_events",
    cluster=settings.CLICKHOUSE_CLUSTER,
)

ADD_EVENT_COUNT_SESSION_REPLAY_EVENTS_TABLE_SQL = lambda: ALTER_SESSION_REPLAY_ADD_EVENT_COUNT_COLUMN.format(
    table_name=SESSION_REPLAY_EVENTS_DATA_TABLE(),
    cluster=settings.CLICKHOUSE_CLUSTER,
)

# migration to add source column to the session replay table
ALTER_SESSION_REPLAY_ADD_SOURCE_COLUMN = """
    ALTER TABLE {table_name} on CLUSTER '{cluster}'
    ADD COLUMN IF NOT EXISTS snapshot_source AggregateFunction(argMin, LowCardinality(Nullable(String)), DateTime64(6, 'UTC'))
"""

ADD_SOURCE_DISTRIBUTED_SESSION_REPLAY_EVENTS_TABLE_SQL = lambda: ALTER_SESSION_REPLAY_ADD_SOURCE_COLUMN.format(
    table_name="session_replay_events",
    cluster=settings.CLICKHOUSE_CLUSTER,
)

ADD_SOURCE_WRITABLE_SESSION_REPLAY_EVENTS_TABLE_SQL = lambda: ALTER_SESSION_REPLAY_ADD_SOURCE_COLUMN.format(
    table_name="writable_session_replay_events",
    cluster=settings.CLICKHOUSE_CLUSTER,
)

ADD_SOURCE_SESSION_REPLAY_EVENTS_TABLE_SQL = lambda: ALTER_SESSION_REPLAY_ADD_SOURCE_COLUMN.format(
    table_name=SESSION_REPLAY_EVENTS_DATA_TABLE(),
    cluster=settings.CLICKHOUSE_CLUSTER,
)

# migration to add all_urls column to the session replay table
ALTER_SESSION_REPLAY_ADD_ALL_URLS_COLUMN = """
    ALTER TABLE {table_name} on CLUSTER '{cluster}'
    ADD COLUMN IF NOT EXISTS all_urls SimpleAggregateFunction(groupUniqArrayArray, Array(String))
"""

ADD_ALL_URLS_DISTRIBUTED_SESSION_REPLAY_EVENTS_TABLE_SQL = lambda: ALTER_SESSION_REPLAY_ADD_ALL_URLS_COLUMN.format(
    table_name="session_replay_events",
    cluster=settings.CLICKHOUSE_CLUSTER,
)

ADD_ALL_URLS_WRITABLE_SESSION_REPLAY_EVENTS_TABLE_SQL = lambda: ALTER_SESSION_REPLAY_ADD_ALL_URLS_COLUMN.format(
    table_name="writable_session_replay_events",
    cluster=settings.CLICKHOUSE_CLUSTER,
)

ADD_ALL_URLS_SESSION_REPLAY_EVENTS_TABLE_SQL = lambda: ALTER_SESSION_REPLAY_ADD_ALL_URLS_COLUMN.format(
    table_name=SESSION_REPLAY_EVENTS_DATA_TABLE(),
    cluster=settings.CLICKHOUSE_CLUSTER,
)

# migration to add library column to the session replay table
ALTER_SESSION_REPLAY_ADD_LIBRARY_COLUMN = """
    ALTER TABLE {table_name} on CLUSTER '{cluster}'
    ADD COLUMN IF NOT EXISTS snapshot_library AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))
"""

ADD_LIBRARY_DISTRIBUTED_SESSION_REPLAY_EVENTS_TABLE_SQL = lambda: ALTER_SESSION_REPLAY_ADD_LIBRARY_COLUMN.format(
    table_name="session_replay_events",
    cluster=settings.CLICKHOUSE_CLUSTER,
)

ADD_LIBRARY_WRITABLE_SESSION_REPLAY_EVENTS_TABLE_SQL = lambda: ALTER_SESSION_REPLAY_ADD_LIBRARY_COLUMN.format(
    table_name="writable_session_replay_events",
    cluster=settings.CLICKHOUSE_CLUSTER,
)

ADD_LIBRARY_SESSION_REPLAY_EVENTS_TABLE_SQL = lambda: ALTER_SESSION_REPLAY_ADD_LIBRARY_COLUMN.format(
    table_name=SESSION_REPLAY_EVENTS_DATA_TABLE(),
    cluster=settings.CLICKHOUSE_CLUSTER,
)

# migration to add retention_period column to the session replay table
ALTER_SESSION_REPLAY_ADD_RETENTION_PERIOD_COLUMN = """
    ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS retention_period Nullable(String)
"""

ADD_RETENTION_PERIOD_DISTRIBUTED_SESSION_REPLAY_EVENTS_TABLE_SQL = (
    lambda: ALTER_SESSION_REPLAY_ADD_RETENTION_PERIOD_COLUMN.format(
        table_name="session_replay_events",
    )
)

ADD_RETENTION_PERIOD_WRITABLE_SESSION_REPLAY_EVENTS_TABLE_SQL = (
    lambda: ALTER_SESSION_REPLAY_ADD_RETENTION_PERIOD_COLUMN.format(
        table_name="writable_session_replay_events",
    )
)

ADD_RETENTION_PERIOD_SESSION_REPLAY_EVENTS_TABLE_SQL = lambda: ALTER_SESSION_REPLAY_ADD_RETENTION_PERIOD_COLUMN.format(
    table_name=SESSION_REPLAY_EVENTS_DATA_TABLE(),
)

# migration to add retention_period column to the session replay table and drop the old string column
ALTER_SESSION_REPLAY_ADD_RETENTION_PERIOD_DAYS_COLUMN = """
    ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS retention_period_days Nullable(Int64)
"""

ADD_RETENTION_PERIOD_DAYS_DISTRIBUTED_SESSION_REPLAY_EVENTS_TABLE_SQL = (
    lambda: ALTER_SESSION_REPLAY_ADD_RETENTION_PERIOD_DAYS_COLUMN.format(
        table_name="session_replay_events",
    )
)

ADD_RETENTION_PERIOD_DAYS_WRITABLE_SESSION_REPLAY_EVENTS_TABLE_SQL = (
    lambda: ALTER_SESSION_REPLAY_ADD_RETENTION_PERIOD_DAYS_COLUMN.format(
        table_name="writable_session_replay_events",
    )
)

ADD_RETENTION_PERIOD_DAYS_SESSION_REPLAY_EVENTS_TABLE_SQL = (
    lambda: ALTER_SESSION_REPLAY_ADD_RETENTION_PERIOD_DAYS_COLUMN.format(
        table_name=SESSION_REPLAY_EVENTS_DATA_TABLE(),
    )
)

ALTER_SESSION_REPLAY_DROP_RETENTION_PERIOD_COLUMN = """
    ALTER TABLE {table_name} DROP COLUMN IF EXISTS retention_period
"""

DROP_RETENTION_PERIOD_DISTRIBUTED_SESSION_REPLAY_EVENTS_TABLE_SQL = (
    lambda: ALTER_SESSION_REPLAY_DROP_RETENTION_PERIOD_COLUMN.format(
        table_name="session_replay_events",
    )
)

DROP_RETENTION_PERIOD_WRITABLE_SESSION_REPLAY_EVENTS_TABLE_SQL = (
    lambda: ALTER_SESSION_REPLAY_DROP_RETENTION_PERIOD_COLUMN.format(
        table_name="writable_session_replay_events",
    )
)

DROP_RETENTION_PERIOD_SESSION_REPLAY_EVENTS_TABLE_SQL = (
    lambda: ALTER_SESSION_REPLAY_DROP_RETENTION_PERIOD_COLUMN.format(
        table_name=SESSION_REPLAY_EVENTS_DATA_TABLE(),
    )
)

# migration to add a TTL policy to the session replay tables
ALTER_SESSION_REPLAY_ADD_TTL = """
    ALTER TABLE {table_name}
        MODIFY TTL addDays(dateTrunc('day', min_first_timestamp), 1) + toIntervalDay(coalesce(retention_period_days, 365))
"""

ADD_TTL_SESSION_REPLAY_EVENTS_TABLE_SQL = lambda: ALTER_SESSION_REPLAY_ADD_TTL.format(
    table_name=SESSION_REPLAY_EVENTS_DATA_TABLE(),
)

ALTER_SESSION_REPLAY_SET_TTL_ONLY_DROP_PARTS = """
    ALTER TABLE {table_name}
        MODIFY SETTING ttl_only_drop_parts=1
"""

SET_TTL_ONLY_DROP_PARTS_SESSION_REPLAY_EVENTS_TABLE_SQL = lambda: ALTER_SESSION_REPLAY_SET_TTL_ONLY_DROP_PARTS.format(
    table_name=SESSION_REPLAY_EVENTS_DATA_TABLE(),
)

# migration to remove TTL policy and change retention period column type
ALTER_SESSION_REPLAY_REMOVE_TTL = """
    ALTER TABLE {table_name}
        REMOVE TTL,
        RESET SETTING ttl_only_drop_parts
"""

REMOVE_TTL_SESSION_REPLAY_EVENTS_TABLE_SQL = lambda: ALTER_SESSION_REPLAY_REMOVE_TTL.format(
    table_name=SESSION_REPLAY_EVENTS_DATA_TABLE(),
)

ALTER_SESSION_REPLAY_DROP_RETENTION_PERIOD_DAYS = """
    ALTER TABLE {table_name}
        DROP COLUMN IF EXISTS retention_period_days
"""

ALTER_SESSION_REPLAY_ADD_RETENTION_PERIOD_DAYS_AGGREGATE_TYPE = """
    ALTER TABLE {table_name}
        ADD COLUMN IF NOT EXISTS retention_period_days SimpleAggregateFunction(max, Nullable(Int64))
"""

DROP_RETENTION_PERIOD_DAYS_DISTRIBUTED_SESSION_REPLAY_EVENTS_TABLE_SQL = (
    lambda: ALTER_SESSION_REPLAY_DROP_RETENTION_PERIOD_DAYS.format(
        table_name="session_replay_events",
    )
)

DROP_RETENTION_PERIOD_DAYS_WRITABLE_SESSION_REPLAY_EVENTS_TABLE_SQL = (
    lambda: ALTER_SESSION_REPLAY_DROP_RETENTION_PERIOD_DAYS.format(
        table_name="writable_session_replay_events",
    )
)

DROP_RETENTION_PERIOD_DAYS_SESSION_REPLAY_EVENTS_TABLE_SQL = (
    lambda: ALTER_SESSION_REPLAY_DROP_RETENTION_PERIOD_DAYS.format(
        table_name=SESSION_REPLAY_EVENTS_DATA_TABLE(),
    )
)

ADD_RETENTION_PERIOD_DAYS_AGGREGATE_TYPE_DISTRIBUTED_SESSION_REPLAY_EVENTS_TABLE_SQL = (
    lambda: ALTER_SESSION_REPLAY_ADD_RETENTION_PERIOD_DAYS_AGGREGATE_TYPE.format(
        table_name="session_replay_events",
    )
)

ADD_RETENTION_PERIOD_DAYS_AGGREGATE_TYPE_WRITABLE_SESSION_REPLAY_EVENTS_TABLE_SQL = (
    lambda: ALTER_SESSION_REPLAY_ADD_RETENTION_PERIOD_DAYS_AGGREGATE_TYPE.format(
        table_name="writable_session_replay_events",
    )
)

ADD_RETENTION_PERIOD_DAYS_AGGREGATE_TYPE_SESSION_REPLAY_EVENTS_TABLE_SQL = (
    lambda: ALTER_SESSION_REPLAY_ADD_RETENTION_PERIOD_DAYS_AGGREGATE_TYPE.format(
        table_name=SESSION_REPLAY_EVENTS_DATA_TABLE(),
    )
)

# =========================
# MIGRATION: Add block columns to support session recording v2 implementation
# This migration adds block_url to the kafka table, and block_first_timestamps, block_last_timestamps, and block_urls
# to the sharded, writable, and distributed session replay events tables.
# The Kafka table only has block_url String (not arrays).
# These columns are required for the v2 session recording implementation.
# =========================

# 1. Sharded table (physical storage)
ALTER_SESSION_REPLAY_ADD_BLOCK_COLUMNS = """
    ALTER TABLE {table_name}
        ADD COLUMN IF NOT EXISTS block_first_timestamps SimpleAggregateFunction(groupArrayArray, Array(DateTime64(6, 'UTC'))),
        ADD COLUMN IF NOT EXISTS block_last_timestamps SimpleAggregateFunction(groupArrayArray, Array(DateTime64(6, 'UTC'))),
        ADD COLUMN IF NOT EXISTS block_urls SimpleAggregateFunction(groupArrayArray, Array(String))
"""
ADD_BLOCK_COLUMNS_SESSION_REPLAY_EVENTS_TABLE_SQL = lambda: ALTER_SESSION_REPLAY_ADD_BLOCK_COLUMNS.format(
    table_name=SESSION_REPLAY_EVENTS_DATA_TABLE(),
)

# 2. Writable table (for writing to sharded table)
ADD_BLOCK_COLUMNS_WRITABLE_SESSION_REPLAY_EVENTS_TABLE_SQL = lambda: ALTER_SESSION_REPLAY_ADD_BLOCK_COLUMNS.format(
    table_name="writable_session_replay_events",
)

# 3. Distributed table (for reading)
ADD_BLOCK_COLUMNS_DISTRIBUTED_SESSION_REPLAY_EVENTS_TABLE_SQL = lambda: ALTER_SESSION_REPLAY_ADD_BLOCK_COLUMNS.format(
    table_name="session_replay_events",
)
