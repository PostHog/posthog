from django.conf import settings

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.flag_evaluations.sql import FLAG_EVALUATIONS_DATA_TABLE

# Raises the TTL from 90 to 92 days. A row dated day D expires when day D + TTL starts in UTC. A "Last 90 days"
# range starts at midnight 90 days back in the team's timezone. That midnight can fall on the UTC day 91 days
# back. A 92-day TTL keeps every UTC day that such a range covers.
#
# MODIFY TTL starts a mutation that recalculates the TTL of every existing part. Without it, a part
# written before this migration keeps expiring on the 90-day schedule. materialize_ttl_recalculate_only
# makes the mutation read only `timestamp` and rewrite only each part's TTL metadata.
#
# Tables in tests have no TTL. See ttl_period().
operations = (
    [
        # A settings-only ALTER changes only the replica that runs it, so this statement runs on every host. Each
        # replica runs the TTL mutation on its own parts. A replica without the setting rewrites every column of
        # every part.
        run_sql_with_exceptions(
            f"ALTER TABLE {FLAG_EVALUATIONS_DATA_TABLE} MODIFY SETTING materialize_ttl_recalculate_only = 1",
            node_roles=[NodeRole.DATA],
            sharded=True,
            is_alter_on_replicated_table=False,
        ),
        # The new TTL applies as soon as the statement returns. With the default alter_sync = 1, the statement also
        # waits for the mutation to finish on this replica, so alter_sync = 0 keeps the deploy from waiting on it.
        # system.mutations shows when the mutation is done.
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
