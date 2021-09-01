LIFECYCLE_SQL = """
SELECT groupArray(day_start) as date, groupArray(counts) as data, status FROM (
    SELECT if(status = 'dormant', toInt64(SUM(counts)) * toInt16(-1), toInt64(SUM(counts))) as counts, day_start, status
    FROM (
        SELECT {trunc_func}(toDateTime(%(date_to)s) - number * %(seconds_in_interval)s) as day_start, toUInt16(0) AS counts, status
        from numbers(%(num_intervals)s) as main
            CROSS JOIN
            (
            SELECT status
            FROM (
            SELECT ['new', 'returning', 'resurrecting', 'dormant'] as status
            ) ARRAY JOIN status
            ) as sec
        ORDER BY status, day_start
        UNION ALL
        SELECT subsequent_day, count(DISTINCT person_id) counts, status FROM (
                SELECT *, if(base_day = toDateTime('0000-00-00 00:00:00'), 'dormant', if(subsequent_day = base_day + INTERVAL {interval}, 'returning', if(subsequent_day > earliest + INTERVAL {interval}, 'resurrecting', 'new'))) as status FROM (
                    SELECT person_id, base_day, min(subsequent_day) as subsequent_day FROM (
                        SELECT person_id, day as base_day, events.subsequent_day as subsequent_day  FROM (
                            SELECT DISTINCT person_id, {trunc_func}(events.timestamp) day FROM events
                            JOIN
                            ({GET_TEAM_PERSON_DISTINCT_IDS}) pdi on events.distinct_id = pdi.distinct_id
                            WHERE team_id = %(team_id)s AND {event_query} {filters}
                            GROUP BY person_id, day HAVING day <= toDateTime(%(date_to)s) AND day >= toDateTime(%(prev_date_from)s)
                        ) base
                        JOIN (
                            SELECT DISTINCT person_id, {trunc_func}(events.timestamp) subsequent_day FROM events
                            JOIN
                            ({GET_TEAM_PERSON_DISTINCT_IDS}) pdi on events.distinct_id = pdi.distinct_id
                            WHERE team_id = %(team_id)s AND {event_query} {filters}
                            GROUP BY person_id, subsequent_day HAVING subsequent_day <= toDateTime(%(date_to)s) AND subsequent_day >= toDateTime(%(prev_date_from)s)
                        ) events ON base.person_id = events.person_id
                        WHERE subsequent_day > base_day
                    )
                    GROUP BY person_id, base_day
                    UNION ALL
                    SELECT person_id, min(day) as base_day, min(day) as subsequent_day  FROM (
                        SELECT DISTINCT person_id, {trunc_func}(events.timestamp) day FROM events
                        JOIN
                        ({GET_TEAM_PERSON_DISTINCT_IDS}) pdi on events.distinct_id = pdi.distinct_id
                        WHERE team_id = %(team_id)s AND {event_query} {filters}
                        GROUP BY person_id, day HAVING day <= toDateTime(%(date_to)s) AND day >= toDateTime(%(prev_date_from)s)
                    ) base
                    GROUP BY person_id
                    UNION ALL
                    SELECT person_id, base_day, subsequent_day FROM (
                        SELECT person_id, total as base_day, day_start as subsequent_day FROM (
                            SELECT DISTINCT person_id, groupArray({trunc_func}(events.timestamp)) day FROM events
                            JOIN
                            ({GET_TEAM_PERSON_DISTINCT_IDS}) pdi on events.distinct_id = pdi.distinct_id
                            WHERE team_id = %(team_id)s AND {event_query} {filters}
                            AND toDateTime(events.timestamp) <= toDateTime(%(date_to)s) AND {trunc_func}(events.timestamp) >= toDateTime(%(date_from)s)
                            GROUP BY person_id
                        ) as e
                        CROSS JOIN (
                            SELECT toDateTime('0000-00-00 00:00:00') AS total, {trunc_func}(toDateTime(%(date_to)s) - number * %(seconds_in_interval)s) as day_start from numbers(%(num_intervals)s)
                        ) as b WHERE has(day, subsequent_day) = 0
                        ORDER BY person_id, subsequent_day ASC
                        ) WHERE
                        ((empty(toString(neighbor(person_id, -1))) OR neighbor(person_id, -1) != person_id) AND subsequent_day != {trunc_func}(toDateTime(%(date_from)s) + INTERVAL {interval} - INTERVAL {sub_interval}))
                        OR
                        ( (neighbor(person_id, -1) = person_id) AND neighbor(subsequent_day, -1) < subsequent_day - INTERVAL {interval})
                    ) e
                JOIN (
                    SELECT DISTINCT person_id, {trunc_func}(min(events.timestamp)) earliest FROM events
                    JOIN
                    ({GET_TEAM_PERSON_DISTINCT_IDS}) pdi on events.distinct_id = pdi.distinct_id
                  WHERE team_id = %(team_id)s AND {event_query} {filters}
                    GROUP BY person_id
                ) earliest ON e.person_id = earliest.person_id
        )
        WHERE subsequent_day <= toDateTime(%(date_to)s) AND subsequent_day >= toDateTime(%(date_from)s)
        GROUP BY subsequent_day, status
    )
    GROUP BY day_start, status
    ORDER BY day_start ASC
)
GROUP BY status
"""

LIFECYCLE_PEOPLE_SQL = """
SELECT person_id FROM (
    SELECT *, if(base_day = toDateTime('0000-00-00 00:00:00'), 'dormant', if(subsequent_day = base_day + INTERVAL {interval}, 'returning', if(subsequent_day > earliest + INTERVAL {interval}, 'resurrecting', 'new'))) as status FROM (
        SELECT person_id, base_day, min(subsequent_day) as subsequent_day FROM (
            SELECT person_id, day as base_day, events.subsequent_day as subsequent_day  FROM (
                SELECT DISTINCT person_id, {trunc_func}(events.timestamp) day FROM events
                JOIN
                ({GET_TEAM_PERSON_DISTINCT_IDS}) pdi on events.distinct_id = pdi.distinct_id
                WHERE team_id = %(team_id)s AND {event_query} {filters}
                GROUP BY person_id, day HAVING day <= toDateTime(%(date_to)s) AND day >= toDateTime(%(prev_date_from)s)
            ) base
            JOIN (
                SELECT DISTINCT person_id, {trunc_func}(events.timestamp) subsequent_day FROM events
                JOIN
                ({GET_TEAM_PERSON_DISTINCT_IDS}) pdi on events.distinct_id = pdi.distinct_id
                WHERE team_id = %(team_id)s AND {event_query} {filters}
                GROUP BY person_id, subsequent_day HAVING subsequent_day <= toDateTime(%(date_to)s) AND subsequent_day >= toDateTime(%(prev_date_from)s)
            ) events ON base.person_id = events.person_id
            WHERE subsequent_day > base_day
        )
        GROUP BY person_id, base_day
        UNION ALL
        SELECT person_id, min(day) as base_day, min(day) as subsequent_day  FROM (
            SELECT DISTINCT person_id, {trunc_func}(events.timestamp) day FROM events
            JOIN
            ({GET_TEAM_PERSON_DISTINCT_IDS}) pdi on events.distinct_id = pdi.distinct_id
            WHERE team_id = %(team_id)s AND {event_query} {filters}
            GROUP BY person_id, day HAVING day <= toDateTime(%(date_to)s) AND day >= toDateTime(%(prev_date_from)s)
        ) base
        GROUP BY person_id
        UNION ALL
        SELECT person_id, base_day, subsequent_day FROM (
            SELECT person_id, dummy as base_day, day_start as subsequent_day FROM (
                SELECT DISTINCT person_id, groupArray({trunc_func}(events.timestamp)) day FROM events
                JOIN
                ({GET_TEAM_PERSON_DISTINCT_IDS}) pdi on events.distinct_id = pdi.distinct_id
                WHERE team_id = %(team_id)s AND {event_query} {filters}
                AND toDateTime(events.timestamp) <= toDateTime(%(date_to)s) AND {trunc_func}(events.timestamp) >= toDateTime(%(date_from)s)
                GROUP BY person_id
            ) as e
            CROSS JOIN (
                SELECT toDateTime('0000-00-00 00:00:00') AS dummy, {trunc_func}(toDateTime(%(date_to)s) - number * %(seconds_in_interval)s) as day_start from numbers(%(num_intervals)s)
            ) as b WHERE has(day, subsequent_day) = 0
            ORDER BY person_id, subsequent_day ASC
            ) WHERE
            ((empty(toString(neighbor(person_id, -1))) OR neighbor(person_id, -1) != person_id) AND subsequent_day != {trunc_func}(toDateTime(%(date_from)s) + INTERVAL {interval} - INTERVAL {sub_interval}))
            OR
            ( (neighbor(person_id, -1) = person_id) AND neighbor(subsequent_day, -1) < subsequent_day - INTERVAL {interval})
        ) e
    JOIN (
        SELECT DISTINCT person_id, {trunc_func}(min(events.timestamp)) earliest FROM events
        JOIN
        ({GET_TEAM_PERSON_DISTINCT_IDS}) pdi on events.distinct_id = pdi.distinct_id
        WHERE team_id = %(team_id)s AND {event_query} {filters}
        GROUP BY person_id
    ) earliest ON e.person_id = earliest.person_id
) e
WHERE status = %(status)s
AND {trunc_func}(toDateTime(%(target_date)s)) = subsequent_day
LIMIT %(limit)s OFFSET %(offset)s
"""
