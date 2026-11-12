from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.metrics import METRICS4_VIEW_SQL
from posthog.run_mode import run_mode

# The view now leaves out Prometheus stale markers. CREATE OR REPLACE VIEW changes no data.
# 0373 created the view on the metrics cluster, which only cloud runs, so the same guard applies here.
operations = [
    run_sql_with_exceptions(METRICS4_VIEW_SQL(), node_roles=[NodeRole.LOGS]),
    *(
        [run_sql_with_exceptions(METRICS4_VIEW_SQL(), node_roles=[NodeRole.METRICS])]
        if run_mode().is_deployed_cloud
        else []
    ),
]
