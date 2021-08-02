TOP_PERSON_PROPS_ARRAY_OF_KEY_SQL = """
SELECT groupArray(value) FROM (
    SELECT value, {aggregate_operation} as count
    FROM
    events e
    INNER JOIN ({GET_TEAM_PERSON_DISTINCT_IDS}) AS pdi ON e.distinct_id = pdi.distinct_id
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
                        arrayMap(k -> trim(BOTH '\"' FROM k.2), JSONExtractKeysAndValuesRaw(properties)) AS array_property_values
                    FROM ({latest_person_sql}) person WHERE team_id = %(team_id)s {person_prop_filters}
                )
                ARRAY JOIN array_property_keys, array_property_values
            ) ep
            WHERE key = %(key)s
        ) ep ON person_id = ep.id
    WHERE
        e.team_id = %(team_id)s {entity_query} {parsed_date_from} {parsed_date_to} {prop_filters}
    GROUP BY value
    ORDER BY count DESC
    LIMIT %(limit)s OFFSET %(offset)s
)
"""
