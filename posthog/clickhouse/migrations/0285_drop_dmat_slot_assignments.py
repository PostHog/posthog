from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

# Tear down the standalone dmat slot-assignments dictionary and its backing table. The
# dynamic-materialized-columns (dmat) feature was removed, so these are no longer created
# (their SQL definitions were deleted from schema.py). Drop the dictionary first — it reads
# from the table.
#
# Scope: this drops ONLY the standalone dict/table. It does NOT drop the `dmat_string_*`
# columns on the events tables. Per the clickhouse-migrations rules, a `DROP COLUMN` must be
# initiated by the ClickHouse team (it can stall and block releases), and the events MVs that
# still SELECT those columns — including the `events_json_ws_mv` no-go zone whose schema is not
# tracked in this repo — must be recreated without them first. Those steps are in the runbook
# beside this file (0285_drop_dmat_slot_assignments.md); a matching `DROP COLUMN` migration
# lands after the team has run them.

operations = [
    run_sql_with_exceptions(
        "DROP DICTIONARY IF EXISTS `dmat_slot_assignments_dict`",
        node_roles=[NodeRole.ALL],
    ),
    run_sql_with_exceptions(
        "DROP TABLE IF EXISTS `dmat_slot_assignments`",
        node_roles=[NodeRole.ALL],
    ),
]
