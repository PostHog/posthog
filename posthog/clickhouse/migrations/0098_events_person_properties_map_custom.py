# This migration was partially applied and will need to be retried/resumed later.

# from posthog.clickhouse.client.connection import NodeRole
# from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
# from posthog.clickhouse.property_groups import property_groups

# operations = [
#     *[
#         run_sql_with_exceptions(statement, node_role=NodeRole.DATA)
#         for statement in property_groups.get_alter_create_statements("sharded_events", "person_properties", "custom")
#     ],
#     *[
#         run_sql_with_exceptions(statement, node_role=NodeRole.ALL)
#         for statement in property_groups.get_alter_create_statements("events", "person_properties", "custom")
#     ],
# ]

operations = []  # type: ignore  # noqa
