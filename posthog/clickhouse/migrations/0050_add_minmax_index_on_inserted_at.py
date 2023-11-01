from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.settings import CLICKHOUSE_CLUSTER

ADD_INDEX_SQL = """
ALTER TABLE sharded_events
ON CLUSTER '{cluster}'
ADD INDEX IF NOT EXISTS events_inserted_at_minmax_index COALESCE(inserted_at, _timestamp)
TYPE minmax;
"""

MATERIALIZE_INDEX_SQL = """
ALTER TABLE sharded_events
ON CLUSTER '{cluster}'
MATERIALIZE INDEX events_inserted_at_minmax_index;
"""

operations = [
    run_sql_with_exceptions(ADD_INDEX_SQL.format(cluster=CLICKHOUSE_CLUSTER)),
    run_sql_with_exceptions(MATERIALIZE_INDEX_SQL.format(cluster=CLICKHOUSE_CLUSTER)),
]
