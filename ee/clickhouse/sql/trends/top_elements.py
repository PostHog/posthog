TOP_ELEMENTS_ARRAY_OF_KEY_SQL = """
SELECT groupArray(value) FROM (
    SELECT
        trim(BOTH '\"' FROM JSONExtractRaw(properties, %(key)s)) as value,
        {aggregate_operation} as count
    FROM events e
    WHERE
        team_id = %(team_id)s {entity_query} {parsed_date_from} {parsed_date_to} {prop_filters}
    GROUP BY value
    ORDER BY count DESC
    LIMIT %(limit)s OFFSET %(offset)s
)
"""
