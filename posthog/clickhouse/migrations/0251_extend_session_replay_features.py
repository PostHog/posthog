from posthog import settings
from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.session_recordings.sql.session_replay_feature_sql import (
    DROP_KAFKA_SESSION_REPLAY_FEATURES_TABLE_SQL,
    DROP_KAFKA_SESSION_REPLAY_FEATURES_WS_TABLE_SQL,
    DROP_SESSION_REPLAY_FEATURES_TABLE_MV_SQL,
    DROP_SESSION_REPLAY_FEATURES_WS_MV_SQL,
    KAFKA_SESSION_REPLAY_FEATURES_TABLE_SQL,
    KAFKA_SESSION_REPLAY_FEATURES_WS_TABLE_SQL,
    SESSION_REPLAY_FEATURES_DATA_TABLE,
    SESSION_REPLAY_FEATURES_TABLE_MV_SQL,
    SESSION_REPLAY_FEATURES_WS_MV_SQL,
)

ADD_COLUMNS_SQL = """
ALTER TABLE {table_name}
    ADD COLUMN IF NOT EXISTS scroll_to_top_count {sum_int},
    ADD COLUMN IF NOT EXISTS backspace_count {sum_int},
    ADD COLUMN IF NOT EXISTS long_idle_gap_count {sum_int},
    ADD COLUMN IF NOT EXISTS login_path_visit_count {sum_int},
    ADD COLUMN IF NOT EXISTS signup_path_visit_count {sum_int},
    ADD COLUMN IF NOT EXISTS checkout_path_visit_count {sum_int},
    ADD COLUMN IF NOT EXISTS cart_path_visit_count {sum_int},
    ADD COLUMN IF NOT EXISTS billing_path_visit_count {sum_int},
    ADD COLUMN IF NOT EXISTS settings_path_visit_count {sum_int},
    ADD COLUMN IF NOT EXISTS account_path_visit_count {sum_int},
    ADD COLUMN IF NOT EXISTS error_path_visit_count {sum_int},
    ADD COLUMN IF NOT EXISTS not_found_path_visit_count {sum_int},
    ADD COLUMN IF NOT EXISTS admin_path_visit_count {sum_int},
    ADD COLUMN IF NOT EXISTS dashboard_path_visit_count {sum_int},
    ADD COLUMN IF NOT EXISTS onboarding_path_visit_count {sum_int},
    ADD COLUMN IF NOT EXISTS cancel_path_visit_count {sum_int},
    ADD COLUMN IF NOT EXISTS refund_path_visit_count {sum_int},
    ADD COLUMN IF NOT EXISTS console_warn_count {sum_int},
    ADD COLUMN IF NOT EXISTS network_4xx_count {sum_int},
    ADD COLUMN IF NOT EXISTS network_5xx_count {sum_int},
    ADD COLUMN IF NOT EXISTS mutation_count {sum_int},
    ADD COLUMN IF NOT EXISTS viewport_resize_count {sum_int},
    ADD COLUMN IF NOT EXISTS touch_event_count {sum_int},
    ADD COLUMN IF NOT EXISTS unique_form_field_count {uniq_int},
    ADD COLUMN IF NOT EXISTS selection_copy_count {sum_int}
"""


def _alter_aggregating(table_name: str) -> str:
    return ADD_COLUMNS_SQL.format(
        table_name=table_name,
        sum_int="SimpleAggregateFunction(sum, Int64)",
        uniq_int="AggregateFunction(uniqExact, Int64)",
    )


_is_cloud = settings.CLOUD_DEPLOYMENT in ("US", "EU", "DEV")

operations = [
    # 1. Drop all materialized views and Kafka tables (MSK + WarpStream) before
    # any schema changes so no in-flight writes hit the tables mid-ALTER.
    # Each DROP uses IF EXISTS so it's safe to re-run.
    run_sql_with_exceptions(DROP_SESSION_REPLAY_FEATURES_TABLE_MV_SQL(), node_roles=[NodeRole.INGESTION_MEDIUM]),
    run_sql_with_exceptions(DROP_KAFKA_SESSION_REPLAY_FEATURES_TABLE_SQL(), node_roles=[NodeRole.INGESTION_MEDIUM]),
    *(
        [
            run_sql_with_exceptions(DROP_SESSION_REPLAY_FEATURES_WS_MV_SQL, node_roles=[NodeRole.INGESTION_MEDIUM]),
            run_sql_with_exceptions(
                DROP_KAFKA_SESSION_REPLAY_FEATURES_WS_TABLE_SQL, node_roles=[NodeRole.INGESTION_MEDIUM]
            ),
        ]
        if _is_cloud
        else []
    ),
    # 2. Add columns to the data tables — sharded source first, then distributed/writable.
    run_sql_with_exceptions(
        _alter_aggregating(SESSION_REPLAY_FEATURES_DATA_TABLE()),
        node_roles=[NodeRole.DATA],
        sharded=True,
        is_alter_on_replicated_table=True,
    ),
    run_sql_with_exceptions(
        _alter_aggregating("session_replay_features"),
        node_roles=[NodeRole.DATA],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
    run_sql_with_exceptions(
        _alter_aggregating("writable_session_replay_features"),
        node_roles=[NodeRole.INGESTION_MEDIUM],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
    # 3. Recreate the Kafka tables and materialized views with the new column set
    # (MSK first, then WarpStream on cloud).
    run_sql_with_exceptions(
        KAFKA_SESSION_REPLAY_FEATURES_TABLE_SQL(on_cluster=False),
        node_roles=[NodeRole.INGESTION_MEDIUM],
    ),
    run_sql_with_exceptions(
        SESSION_REPLAY_FEATURES_TABLE_MV_SQL(on_cluster=False),
        node_roles=[NodeRole.INGESTION_MEDIUM],
    ),
    *(
        [
            run_sql_with_exceptions(
                KAFKA_SESSION_REPLAY_FEATURES_WS_TABLE_SQL(), node_roles=[NodeRole.INGESTION_MEDIUM]
            ),
            run_sql_with_exceptions(SESSION_REPLAY_FEATURES_WS_MV_SQL(), node_roles=[NodeRole.INGESTION_MEDIUM]),
        ]
        if _is_cloud
        else []
    ),
]
