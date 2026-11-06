from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.metrics.metrics2 import (
    METRIC_SERIES2_ADD_LAST_SEEN_INDEX_SQL,
    METRIC_SERIES2_MATERIALIZE_LAST_SEEN_INDEX_SQL,
)

# The overview and the names picker filter `metric_series2` on `last_seen`, which is not in
# the sort key, so every load scans the team's whole series table. Rows land in parts by
# insert time, so a part's `last_seen` range tracks its age and a minmax index lets a
# one-day window skip the old parts that hold most of the rows.
#
# MATERIALIZE is what makes that true for the parts that already exist; without it only
# parts written after the ADD carry the index, and those are the small recent ones a
# window would read anyway.
operations = [
    run_sql_with_exceptions(
        METRIC_SERIES2_ADD_LAST_SEEN_INDEX_SQL(),
        node_roles=[NodeRole.LOGS],
        sharded=False,
        is_alter_on_replicated_table=True,
    ),
    run_sql_with_exceptions(
        METRIC_SERIES2_MATERIALIZE_LAST_SEEN_INDEX_SQL(),
        node_roles=[NodeRole.LOGS],
        sharded=False,
        is_alter_on_replicated_table=True,
    ),
]
