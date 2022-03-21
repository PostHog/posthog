TOP_ELEMENTS_ARRAY_OF_KEY_SQL = """
SELECT groupArray(value) FROM (
    SELECT
        {value_expression},
        {aggregate_operation} as count
    FROM events e
    {person_join_clauses}
    {groups_join_clauses}
    WHERE
        team_id = %(team_id)s {entity_query} {parsed_date_from} {parsed_date_to} {prop_filters}
    GROUP BY value
    ORDER BY count DESC
    LIMIT %(limit)s OFFSET %(offset)s
)
"""
