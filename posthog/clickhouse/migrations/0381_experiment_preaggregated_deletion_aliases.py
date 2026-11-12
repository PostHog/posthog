from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.preaggregation.experiment_exposures_sql import (
    DISTRIBUTED_EXPERIMENT_EXPOSURES_TABLE,
    SHARDED_EXPERIMENT_EXPOSURES_TABLE,
)
from posthog.clickhouse.preaggregation.experiment_metric_events_sql import (
    DISTRIBUTED_EXPERIMENT_METRIC_EVENTS_TABLE,
    SHARDED_EXPERIMENT_METRIC_EVENTS_TABLE,
)

# Adds the column names the deletion sweep matches on (see posthog/dags/deletes.py) to both
# experiment precompute tables, as aliases of the columns that already hold those values, and a
# NULL inserted_at. An alias stores nothing, so the ALTER is metadata only. The SQL files carry the
# rationale.
#
# Unqualified table names, as in 0365, so the ALTER reaches the tables in the configured database.
ADD_EXPOSURES_ALIASES = (
    "ADD COLUMN IF NOT EXISTS timestamp DateTime64(6, 'UTC') ALIAS first_exposure_time, "
    "ADD COLUMN IF NOT EXISTS uuid UUID ALIAS exposure_event_uuid, "
    "ADD COLUMN IF NOT EXISTS inserted_at Nullable(DateTime64(6, 'UTC')) ALIAS NULL"
)
ADD_METRIC_EVENTS_ALIASES = (
    "ADD COLUMN IF NOT EXISTS uuid UUID ALIAS event_uuid, "
    "ADD COLUMN IF NOT EXISTS inserted_at Nullable(DateTime64(6, 'UTC')) ALIAS NULL"
)

operations = [
    run_sql_with_exceptions(
        f"ALTER TABLE {SHARDED_EXPERIMENT_EXPOSURES_TABLE()} {ADD_EXPOSURES_ALIASES}",
        node_roles=[NodeRole.DATA],
        sharded=True,
        is_alter_on_replicated_table=True,
    ),
    run_sql_with_exceptions(
        f"ALTER TABLE {DISTRIBUTED_EXPERIMENT_EXPOSURES_TABLE()} {ADD_EXPOSURES_ALIASES}",
        node_roles=[NodeRole.DATA],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
    run_sql_with_exceptions(
        f"ALTER TABLE {SHARDED_EXPERIMENT_METRIC_EVENTS_TABLE()} {ADD_METRIC_EVENTS_ALIASES}",
        node_roles=[NodeRole.AUX],
        sharded=False,
        is_alter_on_replicated_table=True,
    ),
    run_sql_with_exceptions(
        f"ALTER TABLE {DISTRIBUTED_EXPERIMENT_METRIC_EVENTS_TABLE()} {ADD_METRIC_EVENTS_ALIASES}",
        node_roles=[NodeRole.DATA, NodeRole.AUX],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
]
