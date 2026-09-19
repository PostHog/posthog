from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.metrics.metrics2 import METRICS2_MODIFY_CODECS_SQL

# A codec change is metadata only: new parts use it on insert and old parts on merge.
operations = [
    run_sql_with_exceptions(
        METRICS2_MODIFY_CODECS_SQL(),
        node_roles=[NodeRole.LOGS],
        sharded=False,
        is_alter_on_replicated_table=True,
    ),
]
