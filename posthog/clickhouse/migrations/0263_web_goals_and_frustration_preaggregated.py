from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.preaggregation.web_goals_preaggregated_sql import (
    DISTRIBUTED_WEB_GOALS_PREAGGREGATED_TABLE_SQL,
    SHARDED_WEB_GOALS_PREAGGREGATED_TABLE_SQL,
)
from posthog.clickhouse.preaggregation.web_stats_frustration_preaggregated_sql import (
    DISTRIBUTED_WEB_STATS_FRUSTRATION_PREAGGREGATED_TABLE_SQL,
    SHARDED_WEB_STATS_FRUSTRATION_PREAGGREGATED_TABLE_SQL,
)

# Both new web-analytics precompute tables ship together as a single
# foundation drop and are applied atomically. Each table follows the same
# 3-op AUX/DATA convention used by `0259_web_stats_preaggregated.py` and the
# other web-analytics precompute migrations:
#
#   1. Sharded data table on AUX — keeps the small precompute storage off
#      the main DATA cluster (these tables are never JOINed against events).
#   2. Distributed read table on DATA — production query path; fan-outs
#      resolve to AUX shards via the engine's `cluster=AUX`.
#   3. Same distributed table on AUX — lets operators run ad-hoc
#      `SELECT … FROM <table>` directly from an AUX node without bouncing
#      through DATA. Same DDL, no production cost.
operations = [
    # ---------------- web_stats_frustration_preaggregated ----------------
    run_sql_with_exceptions(
        SHARDED_WEB_STATS_FRUSTRATION_PREAGGREGATED_TABLE_SQL(),
        node_roles=[NodeRole.AUX],
        sharded=True,
    ),
    run_sql_with_exceptions(
        DISTRIBUTED_WEB_STATS_FRUSTRATION_PREAGGREGATED_TABLE_SQL(),
        node_roles=[NodeRole.DATA],
    ),
    run_sql_with_exceptions(
        DISTRIBUTED_WEB_STATS_FRUSTRATION_PREAGGREGATED_TABLE_SQL(),
        node_roles=[NodeRole.AUX],
    ),
    # ---------------- web_goals_preaggregated ----------------
    run_sql_with_exceptions(
        SHARDED_WEB_GOALS_PREAGGREGATED_TABLE_SQL(),
        node_roles=[NodeRole.AUX],
        sharded=True,
    ),
    run_sql_with_exceptions(
        DISTRIBUTED_WEB_GOALS_PREAGGREGATED_TABLE_SQL(),
        node_roles=[NodeRole.DATA],
    ),
    run_sql_with_exceptions(
        DISTRIBUTED_WEB_GOALS_PREAGGREGATED_TABLE_SQL(),
        node_roles=[NodeRole.AUX],
    ),
]
