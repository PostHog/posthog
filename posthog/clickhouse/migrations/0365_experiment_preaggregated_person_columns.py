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

# Adds distinct_id and person_id to both experiment precompute tables. The SQL files carry the
# rationale. person_id has a DEFAULT expression, so existing parts read it as their entity_id
# without a rewrite.
#
# Unqualified table names, as in 0358, so the ALTER reaches the tables in the configured database.
# Positioned rather than appended, so the column order matches the declarative schema.
ADD_PERSON_COLUMNS = (
    "ADD COLUMN IF NOT EXISTS distinct_id String AFTER entity_id, "
    "ADD COLUMN IF NOT EXISTS person_id UUID DEFAULT toUUIDOrZero(entity_id) AFTER distinct_id"
)

operations = [
    run_sql_with_exceptions(
        f"ALTER TABLE {SHARDED_EXPERIMENT_EXPOSURES_TABLE()} {ADD_PERSON_COLUMNS}",
        node_roles=[NodeRole.DATA],
        sharded=True,
        is_alter_on_replicated_table=True,
    ),
    run_sql_with_exceptions(
        f"ALTER TABLE {DISTRIBUTED_EXPERIMENT_EXPOSURES_TABLE()} {ADD_PERSON_COLUMNS}",
        node_roles=[NodeRole.DATA],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
    run_sql_with_exceptions(
        f"ALTER TABLE {SHARDED_EXPERIMENT_METRIC_EVENTS_TABLE()} {ADD_PERSON_COLUMNS}",
        node_roles=[NodeRole.AUX],
        sharded=False,
        is_alter_on_replicated_table=True,
    ),
    run_sql_with_exceptions(
        f"ALTER TABLE {DISTRIBUTED_EXPERIMENT_METRIC_EVENTS_TABLE()} {ADD_PERSON_COLUMNS}",
        node_roles=[NodeRole.DATA, NodeRole.AUX],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
]
