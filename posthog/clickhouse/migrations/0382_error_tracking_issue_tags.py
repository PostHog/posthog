from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

from products.error_tracking.backend.sql import (
    ERROR_TRACKING_ISSUE_TAGS_MV_SQL,
    ERROR_TRACKING_ISSUE_TAGS_TABLE_SQL,
    KAFKA_ERROR_TRACKING_ISSUE_TAGS_TABLE_SQL,
    RAW_ERROR_TRACKING_ISSUE_TAGS_TABLE_SQL,
    WRITABLE_ERROR_TRACKING_ISSUE_TAGS_TABLE_SQL,
)

operations = [
    run_sql_with_exceptions(RAW_ERROR_TRACKING_ISSUE_TAGS_TABLE_SQL(), node_roles=[NodeRole.AUX]),
    run_sql_with_exceptions(ERROR_TRACKING_ISSUE_TAGS_TABLE_SQL(), node_roles=[NodeRole.AUX, NodeRole.DATA]),
    run_sql_with_exceptions(
        WRITABLE_ERROR_TRACKING_ISSUE_TAGS_TABLE_SQL(), node_roles=[NodeRole.INGESTION_SMALL], require_hosts=True
    ),
    run_sql_with_exceptions(
        KAFKA_ERROR_TRACKING_ISSUE_TAGS_TABLE_SQL(), node_roles=[NodeRole.INGESTION_SMALL], require_hosts=True
    ),
    run_sql_with_exceptions(
        ERROR_TRACKING_ISSUE_TAGS_MV_SQL(), node_roles=[NodeRole.INGESTION_SMALL], require_hosts=True
    ),
]
