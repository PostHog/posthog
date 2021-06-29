FUNNEL_SQL = """
SELECT max_step {top_level_groupby}, count(1), groupArray(100)(id) FROM (
    SELECT
        pid.person_id as id,
        {extra_select}
        windowFunnel({within_time})(toUInt64(toUnixTimestamp64Micro(timestamp)),
            {steps}
        ) as max_step
    FROM 
        events
    JOIN (
        SELECT person_id, distinct_id FROM ({latest_distinct_id_sql}) WHERE team_id = %(team_id)s
    ) as pid
    ON pid.distinct_id = events.distinct_id
    WHERE
        team_id = %(team_id)s {filters} {parsed_date_from} {parsed_date_to}
        AND event IN %(events)s
    GROUP BY pid.person_id {extra_groupby}
)
WHERE max_step > 0
GROUP BY max_step {top_level_groupby}
ORDER BY max_step {top_level_groupby} ASC
;
"""

FUNNEL_PERSONS_SQL = """
SELECT max_step, id
FROM
(
    SELECT
        pid.person_id as id,
        {extra_select}
        windowFunnel({within_time})(toUInt64(toUnixTimestamp64Micro(timestamp)),
            {steps}
        ) as max_step
    FROM 
        events
    JOIN (
        SELECT person_id, distinct_id FROM ({latest_distinct_id_sql}) WHERE team_id = %(team_id)s
    ) as pid
    ON pid.distinct_id = events.distinct_id
    WHERE
        team_id = %(team_id)s
        {filters}
        {parsed_date_from}
        {parsed_date_to}
        AND event IN %(events)s
    GROUP BY pid.person_id {extra_groupby}
)
WHERE max_step > 0
GROUP BY max_step, id
ORDER BY max_step ASC
limit 100
offset {offset}
;
"""

FUNNEL_INNER_EVENT_STEPS_QUERY = """
SELECT 
person_id,
timestamp,
{steps}
{select_prop}
FROM 
({event_query})
WHERE ({steps_condition})
{extra_conditions}
"""
