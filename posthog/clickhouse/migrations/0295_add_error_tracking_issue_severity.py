"""AUTO-GENERATED from the declarative HCL by posthog/clickhouse/hcl/codegen/gen_migration.py.
Placement (node_roles) is derived from the node composition manifest; review before committing.
"""

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.run_mode import run_mode

from products.error_tracking.backend.sql import (
    ERROR_TRACKING_FINGERPRINT_ISSUE_STATE_KAFKA_TABLE,
    ERROR_TRACKING_FINGERPRINT_ISSUE_STATE_MV,
    ERROR_TRACKING_FINGERPRINT_ISSUE_STATE_MV_SQL,
    ERROR_TRACKING_FINGERPRINT_ISSUE_STATE_WS_KAFKA_TABLE,
    ERROR_TRACKING_FINGERPRINT_ISSUE_STATE_WS_MV,
    ERROR_TRACKING_FINGERPRINT_ISSUE_STATE_WS_MV_SQL,
    KAFKA_ERROR_TRACKING_FINGERPRINT_ISSUE_STATE_TABLE_SQL,
    KAFKA_ERROR_TRACKING_FINGERPRINT_ISSUE_STATE_WS_TABLE_SQL,
)

operations = [
    run_sql_with_exceptions(
        "ALTER TABLE raw_error_tracking_fingerprint_issue_state "
        "ADD COLUMN IF NOT EXISTS issue_severity Nullable(String) AFTER issue_status",
        node_roles=[NodeRole.AUX],
        sharded=False,
        is_alter_on_replicated_table=True,
    ),
    run_sql_with_exceptions(
        "ALTER TABLE writable_error_tracking_fingerprint_issue_state "
        "ADD COLUMN IF NOT EXISTS issue_severity Nullable(String) AFTER issue_status",
        node_roles=[NodeRole.AUX],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
    run_sql_with_exceptions(
        "ALTER TABLE error_tracking_fingerprint_issue_state "
        "ADD COLUMN IF NOT EXISTS issue_severity Nullable(String) AFTER issue_status",
        node_roles=[NodeRole.DATA, NodeRole.AUX],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
] + (
    [
        run_sql_with_exceptions(
            "ALTER TABLE writable_error_tracking_fingerprint_issue_state "
            "ADD COLUMN IF NOT EXISTS issue_severity Nullable(String) AFTER issue_status",
            node_roles=[NodeRole.INGESTION_SMALL],
            sharded=False,
            is_alter_on_replicated_table=False,
        ),
        run_sql_with_exceptions(
            f"DROP TABLE IF EXISTS {ERROR_TRACKING_FINGERPRINT_ISSUE_STATE_WS_MV}",
            node_roles=[NodeRole.INGESTION_SMALL],
        ),
        run_sql_with_exceptions(
            f"DROP TABLE IF EXISTS {ERROR_TRACKING_FINGERPRINT_ISSUE_STATE_WS_KAFKA_TABLE}",
            node_roles=[NodeRole.INGESTION_SMALL],
        ),
        run_sql_with_exceptions(
            KAFKA_ERROR_TRACKING_FINGERPRINT_ISSUE_STATE_WS_TABLE_SQL(),
            node_roles=[NodeRole.INGESTION_SMALL],
        ),
        run_sql_with_exceptions(
            ERROR_TRACKING_FINGERPRINT_ISSUE_STATE_WS_MV_SQL(),
            node_roles=[NodeRole.INGESTION_SMALL],
        ),
    ]
    if run_mode().is_deployed_cloud
    else [
        run_sql_with_exceptions(
            f"DROP TABLE IF EXISTS {ERROR_TRACKING_FINGERPRINT_ISSUE_STATE_MV}",
            node_roles=[NodeRole.AUX],
        ),
        run_sql_with_exceptions(
            f"DROP TABLE IF EXISTS {ERROR_TRACKING_FINGERPRINT_ISSUE_STATE_KAFKA_TABLE}",
            node_roles=[NodeRole.AUX],
        ),
        run_sql_with_exceptions(
            KAFKA_ERROR_TRACKING_FINGERPRINT_ISSUE_STATE_TABLE_SQL(),
            node_roles=[NodeRole.AUX],
        ),
        run_sql_with_exceptions(
            ERROR_TRACKING_FINGERPRINT_ISSUE_STATE_MV_SQL(),
            node_roles=[NodeRole.AUX],
        ),
    ]
)
