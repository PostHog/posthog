TOP_PERSON_PROPS_ARRAY_OF_KEY_SQL = """
SELECT groupArray(value) FROM (
    SELECT {value_expression} as value, {aggregate_operation} as count
    FROM
    events e
    INNER JOIN ({GET_TEAM_PERSON_DISTINCT_IDS}) AS pdi ON e.distinct_id = pdi.distinct_id
    INNER JOIN
        (
            {person_query}
        ) ep ON person_id = ep.id
    WHERE
        e.team_id = %(team_id)s {entity_query} {parsed_date_from} {parsed_date_to} {prop_filters}
    GROUP BY value
    ORDER BY count DESC
    LIMIT %(limit)s OFFSET %(offset)s
)
"""
