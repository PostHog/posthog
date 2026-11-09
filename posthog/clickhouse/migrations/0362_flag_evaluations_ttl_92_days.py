from django.conf import settings

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.flag_evaluations.sql import FLAG_EVALUATIONS_DATA_TABLE

# Raises the TTL from 90 to 92 days. A row dated day D expires when day D + TTL starts in UTC. A "Last 90 days"
# range starts at midnight 90 days back in the team's timezone. That midnight can fall on the UTC day 91 days
# back. A 92-day TTL keeps every UTC day that such a range covers.
#
# MODIFY TTL starts a mutation that recalculates the TTL of every existing part. Without it, a part
# written before this migration keeps expiring on the 90-day schedule. The table has only a row TTL and
# ttl_only_drop_parts = 1, so the mutation reads only `timestamp` and rewrites only each part's TTL metadata.
#
# Tables in tests have no TTL. See ttl_period().
operations = (
    [
        # A settings-only ALTER changes only the replica that runs it, so this statement runs on every host. Each
        # replica runs the TTL mutation on its own parts. The setting keeps a TTL mutation from rewriting columns
        # if the table later gains a column TTL or loses ttl_only_drop_parts.
        run_sql_with_exceptions(
            f"ALTER TABLE {FLAG_EVALUATIONS_DATA_TABLE} MODIFY SETTING materialize_ttl_recalculate_only = 1",
            node_roles=[NodeRole.DATA],
            sharded=True,
            is_alter_on_replicated_table=False,
        ),
        # With alter_sync = 0, the statement returns once the ALTER is in Keeper. Each replica switches to the new
        # TTL when its replication queue runs the ALTER_METADATA entry. The mutation then recalculates the TTL of
        # each existing part. With the default alter_sync = 1, the deploy would wait for both steps on this replica.
        # system.tables and system.mutations on each replica show when each step is done.
        run_sql_with_exceptions(
            f"ALTER TABLE {FLAG_EVALUATIONS_DATA_TABLE} MODIFY TTL toDate(timestamp) + INTERVAL 92 DAY "
            "SETTINGS materialize_ttl_after_modify = 1, alter_sync = 0",
            node_roles=[NodeRole.DATA],
            sharded=True,
            is_alter_on_replicated_table=True,
        ),
    ]
    if not settings.TEST
    else []
)
