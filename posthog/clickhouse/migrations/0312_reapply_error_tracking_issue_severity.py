from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.run_mode import run_mode

from products.error_tracking.backend.sql import (
    DROP_ERROR_TRACKING_FINGERPRINT_ISSUE_STATE_WS_KAFKA_TABLE_SQL,
    DROP_ERROR_TRACKING_FINGERPRINT_ISSUE_STATE_WS_MV_SQL,
    ERROR_TRACKING_FINGERPRINT_ISSUE_STATE_WS_MV_SQL,
    KAFKA_ERROR_TRACKING_FINGERPRINT_ISSUE_STATE_WS_TABLE_SQL,
    WRITABLE_ERROR_TRACKING_FINGERPRINT_ISSUE_STATE_TABLE_SQL,
)

operations = [
    run_sql_with_exceptions(
        WRITABLE_ERROR_TRACKING_FINGERPRINT_ISSUE_STATE_TABLE_SQL(),
        node_roles=[NodeRole.INGESTION_SMALL],
        require_hosts=True,
    ),
    run_sql_with_exceptions(
        "ALTER TABLE writable_error_tracking_fingerprint_issue_state "
        "ADD COLUMN IF NOT EXISTS issue_severity Nullable(String) AFTER issue_status",
        node_roles=[NodeRole.INGESTION_SMALL],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
] + (
    [
        run_sql_with_exceptions(
            DROP_ERROR_TRACKING_FINGERPRINT_ISSUE_STATE_WS_MV_SQL,
            node_roles=[NodeRole.INGESTION_SMALL],
        ),
        run_sql_with_exceptions(
            DROP_ERROR_TRACKING_FINGERPRINT_ISSUE_STATE_WS_KAFKA_TABLE_SQL,
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
    else []
)
