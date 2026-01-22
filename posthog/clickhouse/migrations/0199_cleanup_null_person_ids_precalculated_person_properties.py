from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions


def CLEANUP_NULL_PERSON_IDS():
    """
    Delete rows with null person_id (00000000-0000-0000-0000-000000000000).
    These are rows that existed before the person_id column was added and cannot be used
    for person-based cohort queries.

    Expected to delete approximately 5M records.

    Uses ALTER TABLE DELETE syntax.
    """
    return """
    ALTER TABLE sharded_precalculated_person_properties
    DELETE WHERE person_id = '00000000-0000-0000-0000-000000000000'
    """


operations = [
    run_sql_with_exceptions(
        CLEANUP_NULL_PERSON_IDS(),
        node_roles=[NodeRole.DATA],
        sharded=True,
    ),
]
