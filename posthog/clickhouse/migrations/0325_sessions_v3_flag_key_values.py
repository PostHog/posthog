from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.raw_sessions.migrations_v3 import (
    ADD_EMAILS,
    ADD_EMAILS_BLOOM_FILTER,
    ADD_FLAG_KEY_VALUES,
    ADD_FLAG_KEY_VALUES_BLOOM_FILTER,
    ADD_HOSTS,
    ADD_HOSTS_BLOOM_FILTER,
)
from posthog.models.raw_sessions.sessions_v3 import (
    DISTRIBUTED_RAW_SESSIONS_TABLE_V3,
    RAW_SESSIONS_CREATE_OR_REPLACE_VIEW_SQL_V3,
    SHARDED_RAW_SESSIONS_TABLE_V3,
    TABLE_BASE_NAME_V3,
    WRITABLE_RAW_SESSIONS_TABLE_V3,
)
from posthog.run_mode import run_mode

operations = [
    run_sql_with_exceptions(
        ADD_FLAG_KEY_VALUES.format(table_name=SHARDED_RAW_SESSIONS_TABLE_V3()),
        node_roles=[NodeRole.DATA],
        sharded=True,
        is_alter_on_replicated_table=True,
    ),
    run_sql_with_exceptions(
        ADD_FLAG_KEY_VALUES.format(table_name=WRITABLE_RAW_SESSIONS_TABLE_V3()),
        node_roles=[NodeRole.DATA],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
    run_sql_with_exceptions(
        ADD_FLAG_KEY_VALUES.format(table_name=DISTRIBUTED_RAW_SESSIONS_TABLE_V3()),
        node_roles=[NodeRole.DATA],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
    run_sql_with_exceptions(
        ADD_FLAG_KEY_VALUES_BLOOM_FILTER.format(table_name=SHARDED_RAW_SESSIONS_TABLE_V3()),
        node_roles=[NodeRole.DATA],
        sharded=True,
        is_alter_on_replicated_table=True,
    ),
    # hosts and emails were only ever added by hand, so the main-cluster copies never got
    # them; the recreated view below selects both, so the columns must exist first.
    run_sql_with_exceptions(
        ADD_HOSTS.format(table_name=SHARDED_RAW_SESSIONS_TABLE_V3()),
        node_roles=[NodeRole.DATA],
        sharded=True,
        is_alter_on_replicated_table=True,
    ),
    run_sql_with_exceptions(
        ADD_HOSTS.format(table_name=WRITABLE_RAW_SESSIONS_TABLE_V3()),
        node_roles=[NodeRole.DATA],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
    run_sql_with_exceptions(
        ADD_HOSTS.format(table_name=DISTRIBUTED_RAW_SESSIONS_TABLE_V3()),
        node_roles=[NodeRole.DATA],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
    run_sql_with_exceptions(
        ADD_EMAILS.format(table_name=SHARDED_RAW_SESSIONS_TABLE_V3()),
        node_roles=[NodeRole.DATA],
        sharded=True,
        is_alter_on_replicated_table=True,
    ),
    run_sql_with_exceptions(
        ADD_EMAILS.format(table_name=WRITABLE_RAW_SESSIONS_TABLE_V3()),
        node_roles=[NodeRole.DATA],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
    run_sql_with_exceptions(
        ADD_EMAILS.format(table_name=DISTRIBUTED_RAW_SESSIONS_TABLE_V3()),
        node_roles=[NodeRole.DATA],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
    run_sql_with_exceptions(
        ADD_HOSTS_BLOOM_FILTER.format(table_name=SHARDED_RAW_SESSIONS_TABLE_V3()),
        node_roles=[NodeRole.DATA],
        sharded=True,
        is_alter_on_replicated_table=True,
    ),
    run_sql_with_exceptions(
        ADD_EMAILS_BLOOM_FILTER.format(table_name=SHARDED_RAW_SESSIONS_TABLE_V3()),
        node_roles=[NodeRole.DATA],
        sharded=True,
        is_alter_on_replicated_table=True,
    ),
    run_sql_with_exceptions(
        RAW_SESSIONS_CREATE_OR_REPLACE_VIEW_SQL_V3(),
        node_roles=[NodeRole.DATA],
    ),
]

# In cloud envs the live copy is the single-shard raw_sessions_v3 MergeTree on the sessions
# satellite cluster (roles/sessions/shared in the HCL); local sessions nodes don't carry it.
if run_mode().is_deployed_cloud:
    operations += [
        run_sql_with_exceptions(
            ADD_FLAG_KEY_VALUES.format(table_name=TABLE_BASE_NAME_V3),
            node_roles=[NodeRole.SESSIONS],
            sharded=False,
            is_alter_on_replicated_table=True,
        ),
        run_sql_with_exceptions(
            ADD_FLAG_KEY_VALUES_BLOOM_FILTER.format(table_name=TABLE_BASE_NAME_V3),
            node_roles=[NodeRole.SESSIONS],
            sharded=False,
            is_alter_on_replicated_table=True,
        ),
    ]
