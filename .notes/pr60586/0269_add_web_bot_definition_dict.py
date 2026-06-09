from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.cluster import NodeRole
from posthog.models.bot_definition.sql import (
    BOT_DEFINITION_DATA_SQL,
    BOT_DEFINITION_DICTIONARY_SQL,
    BOT_DEFINITION_DISTRIBUTED_TABLE_SQL,
    BOT_DEFINITION_TABLE_SQL,
    TRUNCATE_BOT_DEFINITION_TABLE_SQL,
)

# Bot detection needs to resolve from two query routes:
#   - DATA: events-table queries (Trends, HogQL editor, custom insights, web-analytics live path)
#   - AUX:  web-analytics preaggregated tables live on the aux cluster; the future preagg query
#           runners resolve the dict there
#
# AUX and DATA have separate ZooKeeper, so a replicated table with the same name created on both
# clusters is really two independent tables that never replicate to each other. To keep a single
# source of truth, we home the data table on AUX only, seed it there, and expose it to DATA via a
# Distributed read table. The dictionary on both clusters sources from that distributed table.
# This mirrors the property_values / session_replay_features layout.
#
# TRUNCATE before INSERT so the migration is idempotent: any re-run, or any follow-up migration
# that re-seeds bot data from a changed BOT_DEFINITIONS, lands on a clean table. BOT_DEFINITIONS in
# Python is the single source of truth.
#
# UDFs (botGetName, botIsBot, etc.) that wrap the dict and the HogQL emission that uses them land in
# a stacked follow-up PR so this migration stays pure ClickHouse infrastructure with no HogQL surface.
DICT_NODE_ROLES = [NodeRole.DATA, NodeRole.AUX]

operations = [
    # 1. Home the seed table on AUX (replicated, single shard).
    run_sql_with_exceptions(BOT_DEFINITION_TABLE_SQL, node_roles=[NodeRole.AUX]),
    # 2. Seed it on a single AUX host — replication propagates the rows. Running the write on every
    #    replica would multiply the rows by the replica count.
    run_sql_with_exceptions(
        TRUNCATE_BOT_DEFINITION_TABLE_SQL,
        node_roles=[NodeRole.AUX],
        is_alter_on_replicated_table=True,
        sharded=False,
    ),
    run_sql_with_exceptions(
        BOT_DEFINITION_DATA_SQL,
        node_roles=[NodeRole.AUX],
        is_alter_on_replicated_table=True,
        sharded=False,
    ),
    # 3. Distributed read table on DATA + AUX, fanning out to the AUX seed table.
    run_sql_with_exceptions(BOT_DEFINITION_DISTRIBUTED_TABLE_SQL, node_roles=DICT_NODE_ROLES),
    # 4. Dictionary on DATA + AUX, sourcing from the distributed table.
    run_sql_with_exceptions(BOT_DEFINITION_DICTIONARY_SQL, node_roles=DICT_NODE_ROLES),
]
