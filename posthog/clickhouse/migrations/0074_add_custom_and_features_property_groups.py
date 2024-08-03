from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.property_groups import sharded_events_property_groups

operations = [
    run_sql_with_exceptions(statement)
    for statement in [
        *sharded_events_property_groups.get_alter_create_statements("custom"),
        *sharded_events_property_groups.get_alter_create_statements("feature_flags"),
    ]
]
