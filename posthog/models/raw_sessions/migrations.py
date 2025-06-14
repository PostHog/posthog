from posthog.models.raw_sessions.sql import SHARDED_RAW_SESSIONS_DATA_TABLE, TABLE_BASE_NAME

# If in doubt how to use these, check out the README at https://github.com/PostHog/posthog/tree/master/posthog/clickhouse/migrations#readme

# perf
ADD_PAGEVIEW_AUTOCAPTURE_SCREEN_UP_TO_2_COLUMN_SQL = """
ALTER TABLE {table_name}

ADD COLUMN IF NOT EXISTS
page_screen_autocapture_uniq_up_to
AggregateFunction(uniqUpTo(1), Nullable(UUID))
AFTER maybe_has_session_replay
"""

DISTRIBUTED_RAW_SESSIONS_ADD_PAGEVIEW_AUTOCAPTURE_SCREEN_UP_TO_2_COLUMN_SQL = (
    lambda: ADD_PAGEVIEW_AUTOCAPTURE_SCREEN_UP_TO_2_COLUMN_SQL.format(
        table_name=TABLE_BASE_NAME,
    )
)

WRITABLE_RAW_SESSIONS_ADD_PAGEVIEW_AUTOCAPTURE_SCREEN_UP_TO_2_COLUMN_SQL = (
    lambda: ADD_PAGEVIEW_AUTOCAPTURE_SCREEN_UP_TO_2_COLUMN_SQL.format(
        table_name="writable_raw_sessions",
    )
)

SHARDED_RAW_SESSIONS_ADD_PAGEVIEW_AUTOCAPTURE_SCREEN_UP_TO_2_COLUMN_SQL = (
    lambda: ADD_PAGEVIEW_AUTOCAPTURE_SCREEN_UP_TO_2_COLUMN_SQL.format(
        table_name=SHARDED_RAW_SESSIONS_DATA_TABLE(),
    )
)

# vitals
ADD_VITALS_LCP_COLUMN_SQL = """
ALTER TABLE {table_name}

ADD COLUMN IF NOT EXISTS
vitals_lcp
AggregateFunction(argMin, Nullable(Float64), DateTime64(6, 'UTC'))
AFTER page_screen_autocapture_uniq_up_to
"""


def DISTRIBUTED_RAW_SESSIONS_ADD_VITALS_LCP_COLUMN_SQL():
    return ADD_VITALS_LCP_COLUMN_SQL.format(
        table_name=TABLE_BASE_NAME,
    )


def WRITABLE_RAW_SESSIONS_ADD_VITALS_LCP_COLUMN_SQL():
    return ADD_VITALS_LCP_COLUMN_SQL.format(
        table_name="writable_raw_sessions",
    )


def SHARDED_RAW_SESSIONS_ADD_VITALS_LCP_COLUMN_SQL():
    return ADD_VITALS_LCP_COLUMN_SQL.format(
        table_name=SHARDED_RAW_SESSIONS_DATA_TABLE(),
    )


# irclid and _kx
ADD_IRCLID_KX_COLUMNS_SQL = """
ALTER TABLE {table_name}

ADD COLUMN IF NOT EXISTS
initial__kx
AggregateFunction(argMin, String, DateTime64(6, 'UTC'))
AFTER vitals_lcp, -- add at the end as it was accidentally added here on prod

ADD COLUMN IF NOT EXISTS
initial_irclid
AggregateFunction(argMin, String, DateTime64(6, 'UTC'))
AFTER initial_ttclid
"""


def DISTRIBUTED_RAW_SESSIONS_ADD_IRCLID_KX_COLUMNS_SQL():
    return ADD_IRCLID_KX_COLUMNS_SQL.format(
        table_name=TABLE_BASE_NAME,
    )


def WRITABLE_RAW_SESSIONS_ADD_IRCLID_KX_COLUMNS_SQL():
    return ADD_IRCLID_KX_COLUMNS_SQL.format(
        table_name="writable_raw_sessions",
    )


def SHARDED_RAW_SESSIONS_ADD_IRCLID_KX_COLUMNS_SQL():
    return ADD_IRCLID_KX_COLUMNS_SQL.format(
        table_name=SHARDED_RAW_SESSIONS_DATA_TABLE(),
    )


# epik, qclid, sccid
ADD_EPIK_QCLID_SCCID_COLUMNS_SQL = """
ALTER TABLE {table_name}

ADD COLUMN IF NOT EXISTS
initial_epik
AggregateFunction(argMin, String, DateTime64(6, 'UTC'))
AFTER initial_irclid,

ADD COLUMN IF NOT EXISTS
initial_qclid
AggregateFunction(argMin, String, DateTime64(6, 'UTC'))
AFTER initial_epik,

ADD COLUMN IF NOT EXISTS
initial_sccid
AggregateFunction(argMin, String, DateTime64(6, 'UTC'))
AFTER initial_qclid
"""


def DISTRIBUTED_RAW_SESSIONS_ADD_EPIK_QCLID_SCCID_COLUMNS_SQL():
    return ADD_EPIK_QCLID_SCCID_COLUMNS_SQL.format(
        table_name=TABLE_BASE_NAME,
    )


def WRITABLE_RAW_SESSIONS_ADD_EPIK_QCLID_SCCID_COLUMNS_SQL():
    return ADD_EPIK_QCLID_SCCID_COLUMNS_SQL.format(
        table_name="writable_raw_sessions",
    )


def SHARDED_RAW_SESSIONS_ADD_EPIK_QCLID_SCCID_COLUMNS_SQL():
    return ADD_EPIK_QCLID_SCCID_COLUMNS_SQL.format(
        table_name=SHARDED_RAW_SESSIONS_DATA_TABLE(),
    )
