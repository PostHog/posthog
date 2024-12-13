from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.property_groups import property_groups

operations = [
    run_sql_with_exceptions(statement)
    for statement in [
        *property_groups.get_alter_create_statements("events", "properties", "custom"),
        *property_groups.get_alter_create_statements("events", "properties", "feature_flags"),
    ]
]
