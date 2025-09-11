from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

ALTER_EVENTS_TABLE_ADD_EPHEMERAL_PROPERTIES_COLUMNS = """
ALTER TABLE {table_name}
    ADD COLUMN IF NOT EXISTS `properties_map_ephemeral` Map(String, String) EPHEMERAL CAST(JSONExtractKeysAndValues(properties, 'String'), 'Map(String, String)'),
    ADD COLUMN IF NOT EXISTS `person_properties_map_ephemeral` Map(String, String) EPHEMERAL CAST(JSONExtractKeysAndValues(person_properties, 'String'), 'Map(String, String)');

"""


def ALTER_EVENTS_TABLE_ADD_EPHEMERAL_PROPERTIES_COLUMNS_SQL():
    return ALTER_EVENTS_TABLE_ADD_EPHEMERAL_PROPERTIES_COLUMNS.format(table_name="sharded_events")


operations = [run_sql_with_exceptions(ALTER_EVENTS_TABLE_ADD_EPHEMERAL_PROPERTIES_COLUMNS_SQL(), sharded=True)]
