from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.preaggregation.experiment_metric_events_sql import (
    DISTRIBUTED_EXPERIMENT_METRIC_EVENTS_TABLE_SQL,
    DROP_EXPERIMENT_METRIC_EVENTS_TABLE_SQL,
    DROP_SHARDED_EXPERIMENT_METRIC_EVENTS_TABLE_SQL,
    SHARDED_EXPERIMENT_METRIC_EVENTS_TABLE_SQL,
)

# The table was created in 0228 with ORDER BY (team_id, job_id, entity_id).
# ReplacingMergeTree deduplicates by the ORDER BY key, so after background
# merges only one row per (team_id, job_id, entity_id) survives. That works
# for mean/ratio metrics (one value per user), but breaks funnel metrics
# which store one row per event — a user with a pageview and a purchase
# needs both rows kept.
#
# Fix: extend ORDER BY to (team_id, job_id, entity_id, timestamp, event_uuid)
# so each event is a distinct key. No data loss — nothing writes to this
# table yet.

operations = [
    # Drop distributed table first (depends on sharded)
    run_sql_with_exceptions(
        DROP_EXPERIMENT_METRIC_EVENTS_TABLE_SQL(),
        node_roles=[NodeRole.AUX, NodeRole.DATA],
    ),
    # Drop sharded table
    run_sql_with_exceptions(
        DROP_SHARDED_EXPERIMENT_METRIC_EVENTS_TABLE_SQL(),
        node_roles=[NodeRole.AUX],
    ),
    # Recreate sharded table with fixed ORDER BY
    run_sql_with_exceptions(
        SHARDED_EXPERIMENT_METRIC_EVENTS_TABLE_SQL(),
        node_roles=[NodeRole.AUX],
    ),
    # Recreate distributed table
    run_sql_with_exceptions(
        DISTRIBUTED_EXPERIMENT_METRIC_EVENTS_TABLE_SQL(),
        node_roles=[NodeRole.AUX, NodeRole.DATA],
    ),
]
