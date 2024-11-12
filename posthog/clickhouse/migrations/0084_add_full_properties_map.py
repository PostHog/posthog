from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.settings import CLICKHOUSE_CLUSTER

ADD_PROPERTIES_ALL_COLUMNS = """
ALTER TABLE {table} ON CLUSTER {cluster}
ADD COLUMN IF NOT EXISTS properties_all Map(String, String) MATERIALIZED CAST(JSONExtractKeysAndValues(properties, 'String'), 'Map(String, String)') COMMENT 'column_materializer::properties_all'
"""

ADD_PERSON_PROPERTIES_ALL_COLUMNS = """
ALTER TABLE {table} ON CLUSTER {cluster}
ADD COLUMN IF NOT EXISTS person_properties_all Map(String, String) MATERIALIZED CAST(JSONExtractKeysAndValues(person_properties, 'String'), 'Map(String, String)') COMMENT 'column_materializer::person_properties_all'
"""



operations = [
    run_sql_with_exceptions(ADD_PROPERTIES_ALL_COLUMNS.format(table="sharded_events", cluster=CLICKHOUSE_CLUSTER)),
    run_sql_with_exceptions(ADD_PROPERTIES_ALL_COLUMNS.format(table="events", cluster=CLICKHOUSE_CLUSTER)),
    run_sql_with_exceptions(ADD_PERSON_PROPERTIES_ALL_COLUMNS.format(table="sharded_events", cluster=CLICKHOUSE_CLUSTER)),
    run_sql_with_exceptions(ADD_PERSON_PROPERTIES_ALL_COLUMNS.format(table="events", cluster=CLICKHOUSE_CLUSTER)),
]
