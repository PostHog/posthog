from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.raw_sessions.migrations_v3 import (
    ADD_EVENT_NAMES,
    ADD_EVENT_NAMES_BLOOM_FILTER,
    ADD_FLAG_KEYS,
    ADD_FLAG_KEYS_BLOOM_FILTER,
    ADD_URLS,
    DROP_URLS,
)
from posthog.models.raw_sessions.sessions_v3 import (
    DISTRIBUTED_RAW_SESSIONS_TABLE_V3,
    SHARDED_RAW_SESSIONS_TABLE_V3,
    WRITABLE_RAW_SESSIONS_TABLE_V3,
)

operations = [
    # add event_names column to sharded table
    run_sql_with_exceptions(
        ADD_EVENT_NAMES.format(table_name=SHARDED_RAW_SESSIONS_TABLE_V3()),
        node_roles=[NodeRole.DATA],
        sharded=True,
        is_alter_on_replicated_table=True,
    ),
    # add event_names column to writable table
    run_sql_with_exceptions(
        ADD_EVENT_NAMES.format(table_name=WRITABLE_RAW_SESSIONS_TABLE_V3()),
        node_roles=[NodeRole.DATA],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
    # add event_names column to distributed table
    run_sql_with_exceptions(
        ADD_EVENT_NAMES.format(table_name=DISTRIBUTED_RAW_SESSIONS_TABLE_V3()),
        node_roles=[NodeRole.DATA, NodeRole.COORDINATOR],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
    # add bloom filter index to sharded table only
    run_sql_with_exceptions(
        ADD_EVENT_NAMES_BLOOM_FILTER.format(table_name=SHARDED_RAW_SESSIONS_TABLE_V3()),
        node_roles=[NodeRole.DATA],
        sharded=True,
        is_alter_on_replicated_table=True,
    ),
    # add flag_keys column to sharded table
    run_sql_with_exceptions(
        ADD_FLAG_KEYS.format(table_name=SHARDED_RAW_SESSIONS_TABLE_V3()),
        node_roles=[NodeRole.DATA],
        sharded=True,
        is_alter_on_replicated_table=True,
    ),
    # add flag_keys column to writable table
    run_sql_with_exceptions(
        ADD_FLAG_KEYS.format(table_name=WRITABLE_RAW_SESSIONS_TABLE_V3()),
        node_roles=[NodeRole.DATA],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
    # add flag_keys column to distributed table
    run_sql_with_exceptions(
        ADD_FLAG_KEYS.format(table_name=DISTRIBUTED_RAW_SESSIONS_TABLE_V3()),
        node_roles=[NodeRole.DATA, NodeRole.COORDINATOR],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
    # add bloom filter index for flag_keys to sharded table only
    run_sql_with_exceptions(
        ADD_FLAG_KEYS_BLOOM_FILTER.format(table_name=SHARDED_RAW_SESSIONS_TABLE_V3()),
        node_roles=[NodeRole.DATA],
        sharded=True,
        is_alter_on_replicated_table=True,
    ),
    # drop urls column from sharded table
    run_sql_with_exceptions(
        DROP_URLS.format(table_name=SHARDED_RAW_SESSIONS_TABLE_V3()),
        node_roles=[NodeRole.DATA],
        sharded=True,
        is_alter_on_replicated_table=True,
    ),
    # add urls column back to sharded table with correct position
    run_sql_with_exceptions(
        ADD_URLS.format(table_name=SHARDED_RAW_SESSIONS_TABLE_V3()),
        node_roles=[NodeRole.DATA],
        sharded=True,
        is_alter_on_replicated_table=True,
    ),
    # drop urls column from writable table
    run_sql_with_exceptions(
        DROP_URLS.format(table_name=WRITABLE_RAW_SESSIONS_TABLE_V3()),
        node_roles=[NodeRole.DATA],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
    # add urls column back to writable table with correct position
    run_sql_with_exceptions(
        ADD_URLS.format(table_name=WRITABLE_RAW_SESSIONS_TABLE_V3()),
        node_roles=[NodeRole.DATA],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
    # drop urls column from distributed table
    run_sql_with_exceptions(
        DROP_URLS.format(table_name=DISTRIBUTED_RAW_SESSIONS_TABLE_V3()),
        node_roles=[NodeRole.DATA, NodeRole.COORDINATOR],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
    # add urls column back to distributed table with correct position
    run_sql_with_exceptions(
        ADD_URLS.format(table_name=DISTRIBUTED_RAW_SESSIONS_TABLE_V3()),
        node_roles=[NodeRole.DATA, NodeRole.COORDINATOR],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
]
