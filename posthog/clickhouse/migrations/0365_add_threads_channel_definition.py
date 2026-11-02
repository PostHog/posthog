from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.channel_type.sql import (
    CHANNEL_DEFINITION_DATA_SQL,
    CHANNEL_DEFINITION_DICTIONARY_NAME,
    CHANNEL_DEFINITION_TABLE_NAME,
)
from posthog.run_mode import RunMode, run_mode

# Loads the "th" and "threads" (Threads) source rows from channel_definitions.json into ClickHouse.
# Queries read channel_definition_dict, not the JSON file, so a new row has no effect until a migration inserts it.
# The steps are the same as 0291, which explains the truncate + reinsert and the sessions-node handling.
operations = [
    run_sql_with_exceptions(
        f"TRUNCATE TABLE IF EXISTS {CHANNEL_DEFINITION_TABLE_NAME}",
        node_roles=[NodeRole.DATA],
        is_alter_on_replicated_table=True,
    ),
    run_sql_with_exceptions(
        CHANNEL_DEFINITION_DATA_SQL(),
        node_roles=[NodeRole.DATA],
        is_alter_on_replicated_table=True,
    ),
    run_sql_with_exceptions(
        f"SYSTEM RELOAD DICTIONARY {CHANNEL_DEFINITION_DICTIONARY_NAME}",
        node_roles=[NodeRole.DATA],
    ),
]

if run_mode() is RunMode.CLOUD_US:
    operations += [
        run_sql_with_exceptions(
            f"TRUNCATE TABLE IF EXISTS {CHANNEL_DEFINITION_TABLE_NAME}",
            node_roles=[NodeRole.SESSIONS],
            is_alter_on_replicated_table=True,
        ),
        run_sql_with_exceptions(
            CHANNEL_DEFINITION_DATA_SQL(),
            node_roles=[NodeRole.SESSIONS],
            is_alter_on_replicated_table=True,
        ),
    ]
if run_mode().is_prod_cloud:
    operations.append(
        run_sql_with_exceptions(
            f"SYSTEM RELOAD DICTIONARY {CHANNEL_DEFINITION_DICTIONARY_NAME}",
            node_roles=[NodeRole.SESSIONS],
        )
    )
