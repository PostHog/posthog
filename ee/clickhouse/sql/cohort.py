from .clickhouse import STORAGE_POLICY, table_engine

FILTER_EVENT_BY_COHORT_SQL = """
SELECT
    events.uuid,
    events.event,
    events.properties,
    events.timestamp,
    events.team_id,
    events.distinct_id,
    events.elements_chain,
    events.created_at
FROM events WHERE distinct_id IN (
    SELECT distinct_id FROM person_distinct_id WHERE person_id IN (
        SELECT person_id FROM {table_name}
    )
)
"""


def create_cohort_mapping_table_sql(table_name: str) -> str:
    return """
        CREATE TABLE IF NOT EXISTS {table_name}
        (
            person_id UUID
        )ENGINE = {engine}
        ORDER BY (person_id)
        {storage_policy}
        """.format(
        table_name=table_name, engine=table_engine(table_name), storage_policy=STORAGE_POLICY
    )


INSERT_INTO_COHORT_TABLE = """
INSERT INTO {table_name} SELECT person_id FROM ({query})
"""

CALCULATE_COHORT_PEOPLE_SQL = """
SELECT distinct_id FROM person_distinct_id where distinct_id IN {query}
"""

FILTER_EVENT_DISTINCT_ID_BY_ACTION_SQL = """
SELECT distinct_id FROM events where uuid IN (
    SELECT uuid FROM {table_name}
)
"""
