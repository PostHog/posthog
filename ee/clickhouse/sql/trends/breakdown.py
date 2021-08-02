BREAKDOWN_QUERY_SQL = """
SELECT groupArray(day_start) as date, groupArray(count) as data, breakdown_value FROM (
    SELECT SUM(total) as count, day_start, breakdown_value FROM (
        SELECT * FROM (
            SELECT
            toUInt16(0) AS total,
            {interval}(toDateTime(%(date_to)s) - number * %(seconds_in_interval)s) as day_start,
            breakdown_value from numbers(%(num_intervals)s) as main
            CROSS JOIN
                (
                    SELECT breakdown_value
                    FROM (
                        SELECT %(values)s as breakdown_value
                    ) ARRAY JOIN breakdown_value
                ) as sec
            ORDER BY breakdown_value, day_start
            UNION ALL
            {inner_sql}
            {none_union}
        )
    )
    GROUP BY day_start, breakdown_value
    ORDER BY breakdown_value, day_start
) GROUP BY breakdown_value
"""

BREAKDOWN_INNER_SQL = """
SELECT
    {aggregate_operation} as total,
    toDateTime({interval_annotation}(timestamp), 'UTC') as day_start,
    {breakdown_value} as breakdown_value
FROM
events e {event_join} {breakdown_filter}
GROUP BY day_start, breakdown_value
"""

BREAKDOWN_ACTIVE_USER_INNER_SQL = """
SELECT counts as total, timestamp as day_start, breakdown_value
FROM (
    SELECT d.timestamp, COUNT(DISTINCT person_id) counts, breakdown_value FROM (
        SELECT toStartOfDay(timestamp) as timestamp FROM events e WHERE team_id = %(team_id)s {parsed_date_from_prev_range} {parsed_date_to} GROUP BY timestamp
    ) d
    CROSS JOIN (
        SELECT toStartOfDay(timestamp) as timestamp, person_id, {breakdown_value} as breakdown_value
        FROM events e
        INNER JOIN ({GET_TEAM_PERSON_DISTINCT_IDS}) as pdi
        ON e.distinct_id = pdi.distinct_id
        {event_join}
        {conditions}
        GROUP BY timestamp, person_id, breakdown_value
    ) e
    WHERE e.timestamp <= d.timestamp AND e.timestamp > d.timestamp - INTERVAL {prev_interval}
    GROUP BY d.timestamp, breakdown_value
    ORDER BY d.timestamp
) WHERE 1 = 1 {parsed_date_from} {parsed_date_to}
"""


BREAKDOWN_AGGREGATE_QUERY_SQL = """
SELECT {aggregate_operation} as total, {breakdown_value} as breakdown_value
FROM
events e {event_join} {breakdown_filter}
GROUP BY breakdown_value
"""

BREAKDOWN_ACTIVE_USER_CONDITIONS_SQL = """
WHERE e.team_id = %(team_id)s {event_filter} {filters} {parsed_date_from_prev_range} {parsed_date_to} {actions_query}
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
                arrayMap(k -> trim(BOTH '\"' FROM (k.2)), JSONExtractKeysAndValuesRaw(properties)) AS array_property_values
            FROM ({latest_person_sql}) person WHERE team_id = %(team_id)s
        )
        ARRAY JOIN array_property_keys, array_property_values
    ) ep
    WHERE key = %(key)s
) ep
ON person_id = ep.id WHERE e.team_id = %(team_id)s {event_filter} {filters} {parsed_date_from} {parsed_date_to}
AND breakdown_value in (%(values)s) {actions_query}
"""

NONE_BREAKDOWN_PERSON_PROP_JOIN_SQL = """
INNER JOIN (
    SELECT * FROM ({latest_person_sql}) ep WHERE team_id = %(team_id)s AND NOT JSONHas(properties, %(key)s)
) ep
ON person_id = ep.id WHERE e.team_id = %(team_id)s {event_filter} {filters} {parsed_date_from} {parsed_date_to}
{actions_query}
"""

BREAKDOWN_PROP_JOIN_SQL = """
WHERE e.team_id = %(team_id)s {event_filter} {filters} {parsed_date_from} {parsed_date_to}
  AND JSONHas(properties, %(key)s)
  AND trim(BOTH '\"' FROM JSONExtractRaw(properties, %(key)s)) in (%(values)s) 
  {actions_query}
"""

NONE_BREAKDOWN_PROP_JOIN_SQL = """
WHERE e.team_id = %(team_id)s {event_filter} {filters} {parsed_date_from} {parsed_date_to}
  AND NOT JSONHas(properties, %(key)s) 
  {actions_query}
"""

BREAKDOWN_COHORT_JOIN_SQL = """
INNER JOIN (
    {cohort_queries}
) ep
ON e.distinct_id = ep.distinct_id where team_id = %(team_id)s {event_filter} {filters} {parsed_date_from} {parsed_date_to} {actions_query}
"""
