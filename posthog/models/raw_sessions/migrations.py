from django.conf import settings

from posthog.models.raw_sessions.sql import RAW_SESSIONS_DATA_TABLE, TABLE_BASE_NAME

ADD_PAGEVIEW_AUTOCAPTURE_SCREEN_UP_TO_2_COLUMN_SQL = """
ALTER TABLE {table_name} on CLUSTER '{cluster}'
ADD COLUMN IF NOT EXISTS
page_screen_autocapture_uniq_up_to
AggregateFunction(uniqUpTo(1), Nullable(UUID))
AFTER maybe_has_session_replay
"""

BASE_RAW_SESSIONS_ADD_PAGEVIEW_AUTOCAPTURE_SCREEN_UP_TO_2_COLUMN_SQL = (
    lambda: ADD_PAGEVIEW_AUTOCAPTURE_SCREEN_UP_TO_2_COLUMN_SQL.format(
        table_name=TABLE_BASE_NAME,
        cluster=settings.CLICKHOUSE_CLUSTER,
    )
)

WRITABLE_RAW_SESSIONS_ADD_PAGEVIEW_AUTOCAPTURE_SCREEN_UP_TO_2_COLUMN_SQL = (
    lambda: ADD_PAGEVIEW_AUTOCAPTURE_SCREEN_UP_TO_2_COLUMN_SQL.format(
        table_name="writable_raw_sessions",
        cluster=settings.CLICKHOUSE_CLUSTER,
    )
)

DISTRIBUTED_RAW_SESSIONS_ADD_EVENT_COUNT_SESSION_REPLAY_EVENTS_TABLE_SQL = (
    lambda: ADD_PAGEVIEW_AUTOCAPTURE_SCREEN_UP_TO_2_COLUMN_SQL.format(
        table_name=RAW_SESSIONS_DATA_TABLE(),
        cluster=settings.CLICKHOUSE_CLUSTER,
    )
)
