from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.metrics.metrics2 import (
    METRICS2_ADD_TIMESTAMP_INDEX_SQL,
    METRICS2_MATERIALIZE_TIMESTAMP_INDEX_SQL,
)

# `time_bucket` in the `metrics2` sort key only narrows a time filter to the hour, so a
# minmax index on `timestamp` lets a query skip the granules inside that hour it does
# not need. MATERIALIZE builds the index for the parts that already exist; without it
# only parts written after the ADD carry it.
operations = [
    run_sql_with_exceptions(
        METRICS2_ADD_TIMESTAMP_INDEX_SQL(),
        node_roles=[NodeRole.LOGS],
        sharded=False,
        is_alter_on_replicated_table=True,
    ),
    run_sql_with_exceptions(
        METRICS2_MATERIALIZE_TIMESTAMP_INDEX_SQL(),
        node_roles=[NodeRole.LOGS],
        sharded=False,
        is_alter_on_replicated_table=True,
    ),
]
