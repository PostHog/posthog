"""Name the source a check came from, so a read of this table does not have to join Postgres.

The column lands before anything writes the table, so every row it ever holds carries a source.
"""

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

from products.alerts_platform.backend.facade.clickhouse import (
    PLATFORM_ALERT_EVENTS_TABLE,
    SHARDED_PLATFORM_ALERT_EVENTS_TABLE,
)

# Positioned rather than appended, so the migrated cluster matches the column order the Python
# definition and the declarative schema both declare. A drift there fails the schema check.
ADD_SOURCE_KIND = "ADD COLUMN IF NOT EXISTS source_kind LowCardinality(String) AFTER occurred_at"

operations = [
    # Not sharded despite the name: aux is one shard with replicas, so the storage table is
    # replicated and the ALTER runs on one host.
    run_sql_with_exceptions(
        f"ALTER TABLE {SHARDED_PLATFORM_ALERT_EVENTS_TABLE} {ADD_SOURCE_KIND}",
        node_roles=[NodeRole.AUX],
        sharded=False,
        is_alter_on_replicated_table=True,
    ),
    run_sql_with_exceptions(
        f"ALTER TABLE {PLATFORM_ALERT_EVENTS_TABLE} {ADD_SOURCE_KIND}",
        node_roles=[NodeRole.DATA, NodeRole.AUX],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
]
