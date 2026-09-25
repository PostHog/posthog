from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.performance.sql import UPDATE_PERFORMANCE_EVENTS_TABLE_TTL_SQL
from posthog.settings import CONSTANCE_CONFIG

operations = [
    run_sql_with_exceptions(
        UPDATE_PERFORMANCE_EVENTS_TABLE_TTL_SQL(
            on_cluster=False,
            weeks=CONSTANCE_CONFIG["RECORDINGS_PERFORMANCE_EVENTS_TTL_WEEKS"][0],
        ),
        node_roles=[NodeRole.DATA],
        sharded=True,
        is_alter_on_replicated_table=True,
    ),
]
