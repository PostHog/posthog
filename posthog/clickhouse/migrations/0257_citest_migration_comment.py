from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.table_engines import MergeTreeEngine, ReplicationScheme

# Throwaway migration used to exercise the "Render CH migration SQL per cloud environment"
# PR comment. Safe to revert once the CI step is verified. Two operations with different
# node roles so the comment shows more than one node-type group.


def CITEST_DATA_TABLE_SQL() -> str:
    engine = MergeTreeEngine("citest_migration_comment", replication_scheme=ReplicationScheme.REPLICATED)
    return f"""
CREATE TABLE IF NOT EXISTS citest_migration_comment
(
    id UInt64,
    created_at DateTime DEFAULT now()
)
ENGINE = {engine}
ORDER BY id
"""


def CITEST_AUX_TABLE_SQL() -> str:
    engine = MergeTreeEngine("citest_migration_comment_aux", replication_scheme=ReplicationScheme.REPLICATED)
    return f"""
CREATE TABLE IF NOT EXISTS citest_migration_comment_aux
(
    id UInt64
)
ENGINE = {engine}
ORDER BY id
"""


operations = [
    run_sql_with_exceptions(
        CITEST_DATA_TABLE_SQL(),
        node_roles=[NodeRole.DATA, NodeRole.COORDINATOR],
    ),
    run_sql_with_exceptions(
        CITEST_AUX_TABLE_SQL(),
        node_roles=[NodeRole.DATA],
    ),
]
