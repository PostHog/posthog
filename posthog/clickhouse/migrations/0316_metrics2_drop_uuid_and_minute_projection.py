from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.metrics.metrics2 import (
    METRICS2_DROP_SERIES_MINUTE_PROJECTION_SQL,
    METRICS2_DROP_UUID_COLUMN_SQL,
    METRICS2_INPUT_TO_METRICS_MV_MODIFY_QUERY,
    METRICS_DISTRIBUTED_DROP_UUID_COLUMN_SQL,
)

# The MV must stop writing `uuid` before the column goes. A DROP COLUMN while the MV
# still selects `uuid` fails every insert from metrics2_input, which stalls the whole
# kafka_metrics_avro2 consumer, not only metrics2.
#
# metrics_distributed reads metrics2, so it must lose `uuid` first. A distributed table
# that declares a column its remote no longer has fails every read through it.
operations = [
    run_sql_with_exceptions(
        METRICS2_DROP_SERIES_MINUTE_PROJECTION_SQL(),
        node_roles=[NodeRole.LOGS],
        sharded=False,
        is_alter_on_replicated_table=True,
    ),
    run_sql_with_exceptions(
        METRICS2_INPUT_TO_METRICS_MV_MODIFY_QUERY(),
        node_roles=[NodeRole.LOGS],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
    run_sql_with_exceptions(
        METRICS_DISTRIBUTED_DROP_UUID_COLUMN_SQL(),
        node_roles=[NodeRole.LOGS],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
    run_sql_with_exceptions(
        METRICS2_DROP_UUID_COLUMN_SQL(),
        node_roles=[NodeRole.LOGS],
        sharded=False,
        is_alter_on_replicated_table=True,
    ),
]
