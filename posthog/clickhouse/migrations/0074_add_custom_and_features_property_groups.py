from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.property_groups import event_property_groups

operations = [
    run_sql_with_exceptions(statement)
    for statement in [
        *event_property_groups.get_alter_table_statements("custom"),
        *event_property_groups.get_alter_table_statements("features"),
    ]
]
