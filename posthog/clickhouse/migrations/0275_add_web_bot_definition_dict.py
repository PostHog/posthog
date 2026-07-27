from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.bot_definition.sql import (
    BOT_DEFINITION_DATA_SQL,
    BOT_DEFINITION_DICTIONARY_SQL,
    BOT_DEFINITION_TABLE_SQL,
    SHARDED_BOT_DEFINITION_TABLE_SQL,
    TRUNCATE_BOT_DEFINITION_TABLE_SQL,
)

# Bot detection runs from two query routes today (the UDFs that consume the dict land in a
# stacked follow-up PR, so this migration is pure ClickHouse infrastructure):
#   - DATA: events-table queries (Trends, HogQL editor, custom insights, web-analytics live path)
#   - AUX:  web-analytics preaggregated tables live on the aux cluster
#
# The data lives in a single table on AUX; DATA reads it through a Distributed table
# (cluster=AUX). Creating a same-named ReplicatedMergeTree on each cluster would not work —
# DATA and AUX have separate ZooKeeper, so the copies would be unrelated tables that drift.
# This mirrors the web-analytics preaggregated tables (see 0256_web_overview_preaggregated).
#
# BOT_DEFINITIONS in Python is the single source of truth. TRUNCATE before INSERT keeps the
# seed idempotent: re-runs and follow-up re-seeds land on a clean table.
operations = [
    # Data table on AUX only.
    run_sql_with_exceptions(SHARDED_BOT_DEFINITION_TABLE_SQL, node_roles=[NodeRole.AUX], sharded=True),
    # Distributed read table on DATA + AUX, resolving to the AUX data via cluster=AUX.
    run_sql_with_exceptions(BOT_DEFINITION_TABLE_SQL, node_roles=[NodeRole.DATA, NodeRole.AUX]),
    # Seed on AUX only. is_alter_on_replicated_table=True runs the write on one host;
    # replication fans it out to the other AUX replica, so rows aren't multiplied per replica.
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
    # Dict on DATA + AUX, sourcing from the Distributed read table.
    run_sql_with_exceptions(BOT_DEFINITION_DICTIONARY_SQL, node_roles=[NodeRole.DATA, NodeRole.AUX]),
]
