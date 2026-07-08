from posthog import settings
from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.query_log_archive import (
    QUERY_LOG_ARCHIVE_BUFFER_OPS_TABLE_SQL,
    WRITABLE_QUERY_LOG_ARCHIVE_OPS_TABLE_SQL,
    WRITABLE_QUERY_LOG_ARCHIVE_TABLE,
)

# Insert a Buffer table (query_log_archive_buffer) in front of sharded_query_log_archive on the
# OPS cluster and route writable_query_log_archive through it, so the many small per-cluster MV
# inserts are batched in memory before flushing to the ReplicatedMergeTree, reducing part churn.
#
# In the cloud, writable_query_log_archive and ops_query_log_archive_mv are config-managed by
# posthog-cloud-infra (ansible managed_schemas), which repoints the writable at the buffer. This
# migration must NOT touch those objects in the cloud or it would fight that config. So in the
# cloud it only creates the buffer (which infra does not manage); the writable repoint happens
# locally only, where posthog-cloud-infra does not run, to keep dev parity.

ALL_ROLES = [
    NodeRole.DATA,
    NodeRole.ENDPOINTS,
    NodeRole.AUX,
    NodeRole.AI_EVENTS,
    NodeRole.SESSIONS,
    NodeRole.OPS,
]

_IS_CLOUD = settings.CLOUD_DEPLOYMENT in ("US", "EU", "DEV")

operations = [
    # Buffer table on OPS, flushing to sharded_query_log_archive. Owned by this migration
    # (not posthog-cloud-infra), so created everywhere — cloud and local.
    run_sql_with_exceptions(QUERY_LOG_ARCHIVE_BUFFER_OPS_TABLE_SQL(), node_roles=[NodeRole.OPS]),
    # Repoint the writable Distributed at the buffer — local only. In the cloud this is done by
    # posthog-cloud-infra. Drop + recreate is safe (Distributed holds no data, not replicated).
    *(
        []
        if _IS_CLOUD
        else [
            run_sql_with_exceptions(f"DROP TABLE IF EXISTS {WRITABLE_QUERY_LOG_ARCHIVE_TABLE}", node_roles=ALL_ROLES),
            run_sql_with_exceptions(WRITABLE_QUERY_LOG_ARCHIVE_OPS_TABLE_SQL(), node_roles=ALL_ROLES),
        ]
    ),
]
