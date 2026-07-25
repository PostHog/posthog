from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.log_entries import LOG_ENTRIES_DISTRIBUTED_TABLE, LOG_ENTRIES_TABLE

# A three-way RENAME rather than `EXCHANGE TABLES`: EXCHANGE relies on the
# renameat2(RENAME_EXCHANGE) syscall, which needs Linux kernel 3.15+, so old self-hosted hosts
# (CentOS/RHEL 7, kernel 3.10) reject it and the migration hard-fails. RENAME uses plain
# renameat and works everywhere. Atomicity isn't needed since 0144 drops the old table next.
EXCHANGE_LOG_ENTRIES_SQL = f"""
RENAME TABLE
    {LOG_ENTRIES_TABLE} TO {LOG_ENTRIES_TABLE}_exchange_tmp,
    {LOG_ENTRIES_DISTRIBUTED_TABLE} TO {LOG_ENTRIES_TABLE},
    {LOG_ENTRIES_TABLE}_exchange_tmp TO {LOG_ENTRIES_DISTRIBUTED_TABLE}
"""

# IF EXISTS keeps a retry idempotent: instances that dropped the view and then hard-failed
# on the table swap re-run the whole migration from the top.
DROP_LOG_ENTRIES_MV_SQL = f"""
DROP VIEW IF EXISTS {LOG_ENTRIES_TABLE}_mv
"""

operations = [
    run_sql_with_exceptions(DROP_LOG_ENTRIES_MV_SQL, node_roles=[NodeRole.DATA]),
    run_sql_with_exceptions(EXCHANGE_LOG_ENTRIES_SQL, node_roles=[NodeRole.DATA]),
]
