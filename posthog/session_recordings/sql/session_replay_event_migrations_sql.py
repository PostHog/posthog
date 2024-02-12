from django.conf import settings

from posthog.session_recordings.sql.session_replay_event_sql import (
    SESSION_REPLAY_EVENTS_DATA_TABLE,
)

DROP_SESSION_REPLAY_EVENTS_TABLE_MV_SQL = (
    lambda: "DROP TABLE IF EXISTS session_replay_events_mv ON CLUSTER {cluster}".format(
        cluster=settings.CLICKHOUSE_CLUSTER,
    )
)

DROP_KAFKA_SESSION_REPLAY_EVENTS_TABLE_SQL = (
    lambda: "DROP TABLE IF EXISTS kafka_session_replay_events ON CLUSTER {cluster}".format(
        cluster=settings.CLICKHOUSE_CLUSTER,
    )
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
