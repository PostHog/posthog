from django.conf import settings

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.heatmaps.sql import ALTER_TABLE_ADD_TTL_PERIOD

"""
Heatmaps table is compressing at >70% but we don't want it to grow unbounded so we are adding a TTL to it.
No TTL in tests, see `ttl_period()`'s definition
"""
operations = (
    [
        run_sql_with_exceptions(
            ALTER_TABLE_ADD_TTL_PERIOD(), is_alter_on_replicated_table=True, node_roles=NodeRole.DATA
        ),
    ]
    if not settings.TEST
    else []
)
