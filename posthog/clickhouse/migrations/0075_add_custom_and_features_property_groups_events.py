# This migration was partially applied and will need to be retried/resumed later, see:
# https://posthog.slack.com/archives/C0185UNBSJZ/p1723489464588849

# from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
# from posthog.clickhouse.property_groups import property_groups

# operations = [
#     run_sql_with_exceptions(statement)
#     for statement in [
#         *property_groups.get_alter_create_statements("events", "properties", "custom"),
#         *property_groups.get_alter_create_statements("events", "properties", "feature_flags"),
#     ]
# ]

operations = []  # type: ignore  # noqa
