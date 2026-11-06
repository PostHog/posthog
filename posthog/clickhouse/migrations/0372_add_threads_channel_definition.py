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
# The steps follow 0291, which explains the truncate + reinsert and the sessions-node handling.
# Unlike 0291, dev also gets the sessions-node steps: dev sessions nodes store their own replicated
# channel_definition, like US, so the DATA write does not reach them.
#
# The truncate and the insert run on one replica. A replica that reloads its dictionary after it applies the
# truncate but before it fetches the insert caches an empty dictionary until the next refresh, up to an hour later.
# So every replica syncs before it reloads. LIGHTWEIGHT waits only for the fetch and drop-range entries.
SYNC_CHANNEL_DEFINITION_REPLICA_SQL = f"SYSTEM SYNC REPLICA {CHANNEL_DEFINITION_TABLE_NAME} LIGHTWEIGHT"

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
    run_sql_with_exceptions(SYNC_CHANNEL_DEFINITION_REPLICA_SQL, node_roles=[NodeRole.DATA]),
    run_sql_with_exceptions(
        f"SYSTEM RELOAD DICTIONARY {CHANNEL_DEFINITION_DICTIONARY_NAME}",
        node_roles=[NodeRole.DATA],
    ),
]

if run_mode() in (RunMode.CLOUD_US, RunMode.CLOUD_DEV):
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
        run_sql_with_exceptions(SYNC_CHANNEL_DEFINITION_REPLICA_SQL, node_roles=[NodeRole.SESSIONS]),
    ]
# EU sessions nodes have no SYNC step because their channel_definition is a Distributed table over the
# main-cluster table, which the DATA sync above already covers. SYNC REPLICA fails on a Distributed table.
if run_mode().is_deployed_cloud:
    operations.append(
        run_sql_with_exceptions(
            f"SYSTEM RELOAD DICTIONARY {CHANNEL_DEFINITION_DICTIONARY_NAME}",
            node_roles=[NodeRole.SESSIONS],
        )
    )
