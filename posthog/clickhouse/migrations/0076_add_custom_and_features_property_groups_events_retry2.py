from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

operations = [
    run_sql_with_exceptions(statement)
    for statement in [
        # property_groups.get_alter_create_statements("events", "properties", "custom")
        "ALTER TABLE events ON CLUSTER posthog ADD COLUMN IF NOT EXISTS properties_group_custom Map(String, String)",
        # property_groups.get_alter_create_statements("events", "properties", "feature_flags")
        "ALTER TABLE events ON CLUSTER posthog ADD COLUMN IF NOT EXISTS properties_group_feature_flags Map(String, String)",
    ]
]
