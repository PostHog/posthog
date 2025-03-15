# Create 3 helper clickhouse objects, the first sharded_event_number_mv is a materialized view using aggregating engine
# for robust team,event,date event counting, the second event_number is a distributed table making it one table
# and the third event_number_v is a view making querying easier (using countMerge under the hood).
from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.event.sql import (
    TEAM_EVENT_NUMBER_DIST_SQL,
    SHARDED_TEAM_EVENT_NUMBER_MV_SQL,
    TEAM_EVENT_NUMBER_VIEW_SQL,
)

operations = [
    run_sql_with_exceptions(SHARDED_TEAM_EVENT_NUMBER_MV_SQL(), node_role=NodeRole.DATA, sharded=True),
    run_sql_with_exceptions(TEAM_EVENT_NUMBER_DIST_SQL(), node_role=NodeRole.ALL),
    run_sql_with_exceptions(TEAM_EVENT_NUMBER_VIEW_SQL(), node_role=NodeRole.ALL),
]
