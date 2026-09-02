from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.settings import CLICKHOUSE_CLUSTER

ADD_PROJECTION_SQL = """
ALTER TABLE sharded_events
ON CLUSTER '{cluster}'
ADD PROJECTION events_inserted_at_projection (
  SELECT * ORDER BY (team_id, inserted_at, event, cityHash64(distinct_id), cityHash64(uuid))
);
"""

MATERIALIZE_PROJECTION_SQL = """
ALTER TABLE sharded_events
ON CLUSTER '{cluster}'
MATERIALIZE PROJECTION events_inserted_at_projection
IN PARTITION '202310';
"""

operations = [
    run_sql_with_exceptions(ADD_PROJECTION_SQL.format(cluster=CLICKHOUSE_CLUSTER)),
    run_sql_with_exceptions(MATERIALIZE_PROJECTION_SQL.format(cluster=CLICKHOUSE_CLUSTER)),
]
