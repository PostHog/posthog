TOP_ELEMENTS_ARRAY_OF_KEY_SQL = """
SELECT groupArray(value) FROM (
    SELECT
        JSONExtractRaw(properties, %(key)s) as value,
        count(*) as count
    FROM events e
    WHERE team_id = %(team_id)s {parsed_date_from} {parsed_date_to}
     AND JSONHas(properties, %(key)s)
    GROUP BY value
    ORDER BY count DESC
    LIMIT %(limit)s
)
"""
