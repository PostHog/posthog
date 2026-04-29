from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

from products.error_tracking.backend.sql import (
    ERROR_TRACKING_FINGERPRINT_ISSUE_STATE_MV_SQL,
    ERROR_TRACKING_FINGERPRINT_ISSUE_STATE_TABLE_SQL,
    KAFKA_ERROR_TRACKING_FINGERPRINT_ISSUE_STATE_TABLE_SQL,
    RAW_ERROR_TRACKING_FINGERPRINT_ISSUE_STATE_TABLE_SQL,
    WRITABLE_ERROR_TRACKING_FINGERPRINT_ISSUE_STATE_TABLE_SQL,
)

operations = [
    run_sql_with_exceptions(
        RAW_ERROR_TRACKING_FINGERPRINT_ISSUE_STATE_TABLE_SQL(),
        node_roles=[NodeRole.AUX],
    ),
    run_sql_with_exceptions(
        WRITABLE_ERROR_TRACKING_FINGERPRINT_ISSUE_STATE_TABLE_SQL(),
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
    run_sql_with_exceptions(
        ERROR_TRACKING_FINGERPRINT_ISSUE_STATE_TABLE_SQL(),
        node_roles=[NodeRole.AUX, NodeRole.DATA],
    ),
]
