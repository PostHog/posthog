from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.preaggregation.experiment_metric_events_sql import (
    DISTRIBUTED_EXPERIMENT_METRIC_EVENTS_TABLE_SQL,
    SHARDED_EXPERIMENT_METRIC_EVENTS_TABLE_SQL,
)

# Idempotent remediation for `experiment_metric_events_preaggregated`.
#
# Prod CH nodes that take INSERTs from the lazy_computation executor are
# reporting code 60 (UNKNOWN_TABLE) on this table, even though 0228 created
# it and 0230 recreated it after the ORDER BY fix. The new
# `lazy_computation_jobs_finished_total{outcome="failed"}` counter surfaces
# every failed INSERT, and on this table every miss-created job is failing.
#
# Re-running both statements is safe — the underlying SQL uses
# `CREATE TABLE IF NOT EXISTS`, so this is a no-op anywhere 0228/0230 landed
# cleanly and creates the missing table where they didn't.

operations = [
    run_sql_with_exceptions(
        SHARDED_EXPERIMENT_METRIC_EVENTS_TABLE_SQL(),
        node_roles=[NodeRole.AUX],
    ),
    run_sql_with_exceptions(
        DISTRIBUTED_EXPERIMENT_METRIC_EVENTS_TABLE_SQL(),
        node_roles=[NodeRole.AUX, NodeRole.DATA],
    ),
]
