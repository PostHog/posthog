from posthog import settings
from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.session_recordings.sql.session_replay_feature_sql import (
    DISTRIBUTED_SESSION_REPLAY_FEATURES_TABLE_SQL,
    DROP_KAFKA_SESSION_REPLAY_FEATURES_TABLE_SQL,
    DROP_KAFKA_SESSION_REPLAY_FEATURES_WS_TABLE_SQL,
    DROP_SESSION_REPLAY_FEATURES_TABLE_MV_SQL,
    DROP_SESSION_REPLAY_FEATURES_WS_MV_SQL,
    KAFKA_SESSION_REPLAY_FEATURES_TABLE_SQL,
    KAFKA_SESSION_REPLAY_FEATURES_WS_TABLE_SQL,
    SESSION_REPLAY_FEATURES_DATA_TABLE,
    SESSION_REPLAY_FEATURES_TABLE_MV_SQL,
    SESSION_REPLAY_FEATURES_WS_MV_SQL,
    UNIQ_COMBINED_PRECISION,
    WRITABLE_SESSION_REPLAY_FEATURES_TABLE_SQL,
)

# ALTER for the underlying sharded data table only — DROP+ADD lets us swap the
# uniqExact unique_* columns for uniqCombined, which has a bounded HLL-backed state.
# The ADD COLUMN IF NOT EXISTS clauses also bring in all the new ML feature columns.
SHARDED_ALTER_SQL = """
ALTER TABLE {table_name}
    DROP COLUMN IF EXISTS unique_url_count,
    DROP COLUMN IF EXISTS unique_click_target_count,
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
    ADD COLUMN IF NOT EXISTS unique_url_count {uniq_string},
    ADD COLUMN IF NOT EXISTS unique_click_target_count {uniq_int},
    ADD COLUMN IF NOT EXISTS unique_form_field_count {uniq_int},
    ADD COLUMN IF NOT EXISTS selection_copy_count {sum_int}
"""


def _alter_sharded() -> str:
    return SHARDED_ALTER_SQL.format(
        table_name=SESSION_REPLAY_FEATURES_DATA_TABLE(),
        sum_int="SimpleAggregateFunction(sum, Int64)",
        uniq_int=f"AggregateFunction(uniqCombined({UNIQ_COMBINED_PRECISION}), Int64)",
        uniq_string=f"AggregateFunction(uniqCombined({UNIQ_COMBINED_PRECISION}), String)",
    )


_is_cloud = settings.CLOUD_DEPLOYMENT in ("US", "EU", "DEV")

operations = [
    # 1. Drop all materialized views and Kafka tables (MSK + WarpStream) before
    run_sql_with_exceptions(DROP_SESSION_REPLAY_FEATURES_TABLE_MV_SQL(), node_roles=[NodeRole.INGESTION_MEDIUM]),
    run_sql_with_exceptions(DROP_KAFKA_SESSION_REPLAY_FEATURES_TABLE_SQL(), node_roles=[NodeRole.INGESTION_MEDIUM]),
    run_sql_with_exceptions(DROP_SESSION_REPLAY_FEATURES_WS_MV_SQL, node_roles=[NodeRole.INGESTION_MEDIUM]),
    run_sql_with_exceptions(DROP_KAFKA_SESSION_REPLAY_FEATURES_WS_TABLE_SQL, node_roles=[NodeRole.INGESTION_MEDIUM]),
    # 2. ALTER the sharded source-of-truth table in place (it holds the actual data).
    run_sql_with_exceptions(
        _alter_sharded(),
        node_roles=[NodeRole.AUX],
        sharded=False,
        is_alter_on_replicated_table=True,
    ),
    # 3. Drop and recreate the Distributed read/write tables. They have no data
    run_sql_with_exceptions(
        "DROP TABLE IF EXISTS session_replay_features",
        node_roles=[NodeRole.AUX],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
    run_sql_with_exceptions(
        DISTRIBUTED_SESSION_REPLAY_FEATURES_TABLE_SQL(on_cluster=False),
        node_roles=[NodeRole.AUX],
    ),
    run_sql_with_exceptions(
        "DROP TABLE IF EXISTS writable_session_replay_features",
        node_roles=[NodeRole.INGESTION_MEDIUM],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
    run_sql_with_exceptions(
        WRITABLE_SESSION_REPLAY_FEATURES_TABLE_SQL(on_cluster=False),
        node_roles=[NodeRole.INGESTION_MEDIUM],
    ),
    # 4. Recreate the Kafka tables and materialized views with the new column set.
    *(
        # Cloud: WarpStream pair only.
        [
            run_sql_with_exceptions(
                KAFKA_SESSION_REPLAY_FEATURES_WS_TABLE_SQL(), node_roles=[NodeRole.INGESTION_MEDIUM]
            ),
            run_sql_with_exceptions(SESSION_REPLAY_FEATURES_WS_MV_SQL(), node_roles=[NodeRole.INGESTION_MEDIUM]),
        ]
        if _is_cloud
        # Non-cloud: MSK pair only.
        else [
            run_sql_with_exceptions(
                KAFKA_SESSION_REPLAY_FEATURES_TABLE_SQL(on_cluster=False),
                node_roles=[NodeRole.INGESTION_MEDIUM],
            ),
            run_sql_with_exceptions(
                SESSION_REPLAY_FEATURES_TABLE_MV_SQL(on_cluster=False),
                node_roles=[NodeRole.INGESTION_MEDIUM],
            ),
        ]
    ),
]
