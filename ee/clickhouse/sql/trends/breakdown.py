BREAKDOWN_QUERY_SQL = """
SELECT groupArray(day_start), groupArray(count), breakdown_value FROM (
    SELECT SUM(total) as count, day_start, breakdown_value FROM (
        SELECT * FROM (
            {null_sql} as main
            CROSS JOIN
                (
                    SELECT breakdown_value
                    FROM (
                        SELECT %(values)s as breakdown_value
                    ) ARRAY JOIN breakdown_value
                ) as sec
            ORDER BY breakdown_value, day_start
            UNION ALL
            SELECT
                {aggregate_operation} as total,
                toDateTime({interval_annotation}(timestamp), 'UTC') as day_start,
                {breakdown_value} as breakdown_value
            FROM
            events e {event_join} {breakdown_filter}
            GROUP BY day_start, breakdown_value
        )
    )
    GROUP BY day_start, breakdown_value
    ORDER BY breakdown_value, day_start
) GROUP BY breakdown_value
"""

BREAKDOWN_AGGREGATE_QUERY_SQL = """
SELECT {aggregate_operation} as total, {breakdown_value} as breakdown_value
FROM
events e {event_join} {breakdown_filter}
GROUP BY breakdown_value
"""


BREAKDOWN_DEFAULT_SQL = """
SELECT groupArray(day_start), groupArray(count) FROM (
    SELECT SUM(total) as count, day_start FROM (
        SELECT * FROM (
            {null_sql} as main
            ORDER BY day_start
            UNION ALL
            SELECT {aggregate_operation} as total, toDateTime({interval_annotation}(timestamp), 'UTC') as day_start
            FROM
            events e {event_join} {breakdown_filter}
            GROUP BY day_start
        )
    )
    GROUP BY day_start
    ORDER BY day_start
)
"""

BREAKDOWN_AGGREGATE_DEFAULT_SQL = """
SELECT {aggregate_operation} as total
FROM
events e {event_join} {breakdown_filter}
"""

BREAKDOWN_CONDITIONS_SQL = """
WHERE team_id = %(team_id)s {event_filter} {filters} {parsed_date_from} {parsed_date_to} {actions_query}
"""

BREAKDOWN_PERSON_PROP_JOIN_SQL = """
INNER JOIN (
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
) ep
ON person_id = ep.id WHERE e.team_id = %(team_id)s {event_filter} {filters} {parsed_date_from} {parsed_date_to}
AND breakdown_value in (%(values)s) {actions_query}
"""


BREAKDOWN_PROP_JOIN_SQL = """
WHERE e.team_id = %(team_id)s {event_filter} {filters} {parsed_date_from} {parsed_date_to}
  AND JSONHas(properties, %(key)s)
  AND JSONExtractRaw(properties, %(key)s) in (%(values)s) {actions_query}
"""

BREAKDOWN_COHORT_JOIN_SQL = """
INNER JOIN (
    {cohort_queries}
) ep
ON e.distinct_id = ep.distinct_id where team_id = %(team_id)s {event_filter} {filters} {parsed_date_from} {parsed_date_to} {actions_query}
"""
