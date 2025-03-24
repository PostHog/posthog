from django.conf import settings

from posthog.clickhouse.cluster import ON_CLUSTER_CLAUSE
from posthog.models.raw_sessions.sql import RAW_SESSIONS_DATA_TABLE, TABLE_BASE_NAME

# perf
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

# vitals
ADD_VITALS_LCP_COLUMN_SQL = """
ALTER TABLE {table_name} on CLUSTER '{cluster}'
ADD COLUMN IF NOT EXISTS
vitals_lcp
AggregateFunction(argMin, Nullable(Float64), DateTime64(6, 'UTC'))
AFTER page_screen_autocapture_uniq_up_to
"""

BASE_RAW_SESSIONS_ADD_VITALS_LCP_COLUMN_SQL = lambda: ADD_VITALS_LCP_COLUMN_SQL.format(
    table_name=TABLE_BASE_NAME,
    cluster=settings.CLICKHOUSE_CLUSTER,
)

WRITABLE_RAW_SESSIONS_ADD_VITALS_LCP_COLUMN_SQL = lambda: ADD_VITALS_LCP_COLUMN_SQL.format(
    table_name="writable_raw_sessions",
    cluster=settings.CLICKHOUSE_CLUSTER,
)

DISTRIBUTED_RAW_SESSIONS_ADD_VITALS_LCP_COLUMN_SQL = lambda: ADD_VITALS_LCP_COLUMN_SQL.format(
    table_name=RAW_SESSIONS_DATA_TABLE(),
    cluster=settings.CLICKHOUSE_CLUSTER,
)

# irclid and _kx
ADD_IRCLID_KX_COLUMNS_SQL = """
ALTER TABLE {table_name} {on_cluster_clause}
ADD COLUMN IF NOT EXISTS
initial__kx
AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
ADD COLUMN IF NOT EXISTS
initial_irclid
AggregateFunction(argMin, String, DateTime64(6, 'UTC'))
AFTER initial_ttclid
"""


def BASE_RAW_SESSIONS_ADD_IRCLID_KX_COLUMNS_SQL(on_cluster=True):
    return ADD_IRCLID_KX_COLUMNS_SQL.format(
        table_name=TABLE_BASE_NAME,
        on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster),
    )


def WRITABLE_RAW_SESSIONS_ADD_IRCLID_KX_COLUMNS_SQL(on_cluster=True):
    return ADD_IRCLID_KX_COLUMNS_SQL.format(
        table_name="writable_raw_sessions",
        on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster),
    )


def DISTRIBUTED_RAW_SESSIONS_ADD_IRCLID_KX_COLUMNS_SQL(on_cluster=True):
    return ADD_IRCLID_KX_COLUMNS_SQL.format(
        table_name=RAW_SESSIONS_DATA_TABLE(),
        on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster),
    )
