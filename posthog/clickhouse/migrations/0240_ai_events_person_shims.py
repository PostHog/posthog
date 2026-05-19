from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.ai_events.person_shims import PERSON_AI_EVENTS_SHIM_SQL, PERSON_DISTINCT_ID2_AI_EVENTS_SHIM_SQL

# Distributed shim tables on NodeRole.AI_EVENTS that forward person joins back
# to the main cluster. Unblocks HogQL queries like
#   SELECT person.properties.$email FROM ai_events
# which previously failed with `Table posthog.person_distinct_id2 does not
# exist` because the real person tables only live on NodeRole.DATA.

operations = [
    run_sql_with_exceptions(
        PERSON_DISTINCT_ID2_AI_EVENTS_SHIM_SQL(),
        node_roles=[NodeRole.AI_EVENTS],
    ),
    run_sql_with_exceptions(
        PERSON_AI_EVENTS_SHIM_SQL(),
        node_roles=[NodeRole.AI_EVENTS],
    ),
]
