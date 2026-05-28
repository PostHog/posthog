from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.preaggregation.retention_actor_event_day_sql import (
    DISTRIBUTED_RETENTION_ACTOR_EVENT_DAY_TABLE_SQL,
    SHARDED_RETENTION_ACTOR_EVENT_DAY_TABLE_SQL,
)

operations = [
    # Sharded data table on AUX. Same precedent as web_stats_preaggregated — the
    # precompute table is small (Phase 1 sizing: ~1.8 GiB/month for the heaviest
    # team) and never JOINed against events, so keeping it off the main DATA cluster
    # avoids contention with the raw events read path.
    run_sql_with_exceptions(
        SHARDED_RETENTION_ACTOR_EVENT_DAY_TABLE_SQL(),
        node_roles=[NodeRole.AUX],
        sharded=True,
    ),
    # Distributed read table on DATA. Production query path fans out from DATA and
    # resolves to AUX shards via the Distributed engine's `cluster=AUX` setting.
    run_sql_with_exceptions(
        DISTRIBUTED_RETENTION_ACTOR_EVENT_DAY_TABLE_SQL(),
        node_roles=[NodeRole.DATA],
    ),
    # Same distributed table also on AUX for ad-hoc debugging — lets operators
    # `SELECT … FROM retention_actor_event_day` directly from an AUX node.
    run_sql_with_exceptions(
        DISTRIBUTED_RETENTION_ACTOR_EVENT_DAY_TABLE_SQL(),
        node_roles=[NodeRole.AUX],
    ),
]
