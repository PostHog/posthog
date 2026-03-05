from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.raw_sessions.migrations_v3 import (
    ADD_EMAILS,
    ADD_EMAILS_BLOOM_FILTER,
    ADD_HOSTS,
    ADD_HOSTS_BLOOM_FILTER,
)
from posthog.models.raw_sessions.sessions_v3 import (
    DISTRIBUTED_RAW_SESSIONS_TABLE_V3,
    SHARDED_RAW_SESSIONS_TABLE_V3,
    WRITABLE_RAW_SESSIONS_TABLE_V3,
)

operations = [
    # add hosts column to sharded table
    run_sql_with_exceptions(
        ADD_HOSTS.format(table_name=SHARDED_RAW_SESSIONS_TABLE_V3()),
        node_roles=[NodeRole.DATA],
        sharded=True,
        is_alter_on_replicated_table=True,
    ),
    # add hosts column to writable table
    run_sql_with_exceptions(
        ADD_HOSTS.format(table_name=WRITABLE_RAW_SESSIONS_TABLE_V3()),
        node_roles=[NodeRole.DATA],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
    # add hosts column to distributed table
    run_sql_with_exceptions(
        ADD_HOSTS.format(table_name=DISTRIBUTED_RAW_SESSIONS_TABLE_V3()),
        node_roles=[NodeRole.DATA, NodeRole.COORDINATOR],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
    # add bloom filter index for hosts to sharded table only
    run_sql_with_exceptions(
        ADD_HOSTS_BLOOM_FILTER.format(table_name=SHARDED_RAW_SESSIONS_TABLE_V3()),
        node_roles=[NodeRole.DATA],
        sharded=True,
        is_alter_on_replicated_table=True,
    ),
    # add emails column to sharded table
    run_sql_with_exceptions(
        ADD_EMAILS.format(table_name=SHARDED_RAW_SESSIONS_TABLE_V3()),
        node_roles=[NodeRole.DATA],
        sharded=True,
        is_alter_on_replicated_table=True,
    ),
    # add emails column to writable table
    run_sql_with_exceptions(
        ADD_EMAILS.format(table_name=WRITABLE_RAW_SESSIONS_TABLE_V3()),
        node_roles=[NodeRole.DATA],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
    # add emails column to distributed table
    run_sql_with_exceptions(
        ADD_EMAILS.format(table_name=DISTRIBUTED_RAW_SESSIONS_TABLE_V3()),
        node_roles=[NodeRole.DATA, NodeRole.COORDINATOR],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
    # add bloom filter index for emails to sharded table only
    run_sql_with_exceptions(
        ADD_EMAILS_BLOOM_FILTER.format(table_name=SHARDED_RAW_SESSIONS_TABLE_V3()),
        node_roles=[NodeRole.DATA],
        sharded=True,
        is_alter_on_replicated_table=True,
    ),
]
