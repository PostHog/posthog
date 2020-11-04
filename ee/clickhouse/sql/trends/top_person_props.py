TOP_PERSON_PROPS_ARRAY_OF_KEY_SQL = """
SELECT groupArray(value) FROM (
    SELECT value, count(*) as count
    FROM
    events e 
    INNER JOIN (SELECT person_id, distinct_id FROM person_distinct_id WHERE team_id = %(team_id)s) as pid ON e.distinct_id = pid.distinct_id
    INNER JOIN
        (
            SELECT * FROM (
                SELECT
                id,
                array_property_keys as key,
                array_property_values as value
                from (
                    SELECT
                        id,
                        arrayMap(k -> toString(k.1), JSONExtractKeysAndValuesRaw(properties)) AS array_property_keys,
                        arrayMap(k -> toString(k.2), JSONExtractKeysAndValuesRaw(properties)) AS array_property_values
                    FROM ({latest_person_sql}) person WHERE team_id = %(team_id)s
                )
                ARRAY JOIN array_property_keys, array_property_values
            ) ep
            WHERE key = %(key)s
        ) ep ON person_id = ep.id WHERE e.team_id = %(team_id)s {parsed_date_from} {parsed_date_to}
    GROUP BY value
    ORDER BY count DESC
    LIMIT %(limit)s
)
"""
