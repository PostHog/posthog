from django.conf import settings

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.query_log_archive import MV_SELECT_SQL, QUERY_LOG_ARCHIVE_NEW_TABLE_SQL
from posthog.clickhouse.table_engines import Distributed


def QUERY_LOG_ARCHIVE_DISTRIBUTED_TABLE_SQL():
    """
    Distributed table on Endpoints cluster that points to the main cluster's query_log_archive.
    """
    return QUERY_LOG_ARCHIVE_NEW_TABLE_SQL(
        table_name="writable_query_log_archive",
        engine=Distributed(data_table="query_log_archive", cluster=settings.CLICKHOUSE_SINGLE_SHARD_CLUSTER),
        include_table_clauses=False,
    )


CREATE_QUERY_LOG_ARCHIVE_MV_ENDPOINTS = f"""
CREATE MATERIALIZED VIEW IF NOT EXISTS query_log_archive_mv
TO writable_query_log_archive
AS {MV_SELECT_SQL}
"""

operations = [
    run_sql_with_exceptions(QUERY_LOG_ARCHIVE_DISTRIBUTED_TABLE_SQL(), node_roles=NodeRole.ENDPOINTS),
    run_sql_with_exceptions(CREATE_QUERY_LOG_ARCHIVE_MV_ENDPOINTS, node_roles=NodeRole.ENDPOINTS),
]
