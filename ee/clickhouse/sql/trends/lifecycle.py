LIFECYCLE_SQL = """
SELECT groupArray(day_start), groupArray(counts), status FROM (
    SELECT SUM(counts) as counts, day_start, status
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
            SELECT * FROM (
                SELECT *, if(base_day = toDateTime('0000-00-00 00:00:00'), 'dormant', if(subsequent_day = base_day + INTERVAL {interval}, 'returning', if(earliest < base_day, 'resurrecting', 'new'))) as status FROM (
                    SELECT distinct_id, base_day, min(subsequent_day) as subsequent_day FROM (
                        SELECT distinct_id, day as base_day, events.subsequent_day as subsequent_day  FROM (
                            SELECT DISTINCT distinct_id, {trunc_func}(events.timestamp) day FROM events WHERE team_id = %(team_id)s AND {event_query}
                            GROUP BY distinct_id, day HAVING day <= toDateTime(%(date_to)s) AND day >= toDateTime(%(prev_date_from)s)
                        ) base
                        JOIN (
                            SELECT DISTINCT distinct_id, {trunc_func}(events.timestamp) subsequent_day FROM events WHERE team_id = %(team_id)s AND {event_query}
                            GROUP BY distinct_id, subsequent_day HAVING subsequent_day <= toDateTime(%(date_to)s) AND subsequent_day >= toDateTime(%(prev_date_from)s)
                        ) events ON base.distinct_id = events.distinct_id 
                        WHERE subsequent_day > base_day
                    )
                    GROUP BY distinct_id, base_day
                    UNION ALL
                    SELECT distinct_id, min(day) as base_day, min(day) as subsequent_day  FROM (
                        SELECT DISTINCT distinct_id, {trunc_func}(events.timestamp) day FROM events WHERE team_id = %(team_id)s AND {event_query}
                        GROUP BY distinct_id, day HAVING day <= toDateTime(%(date_to)s) AND day >= toDateTime(%(prev_date_from)s)
                    ) base
                    GROUP BY distinct_id
                    UNION ALL
                    SELECT distinct_id, base_day, subsequent_day FROM (
                        SELECT distinct_id, total as base_day, day_start as subsequent_day FROM (
                            SELECT DISTINCT distinct_id, groupArray({trunc_func}(events.timestamp)) day FROM events WHERE team_id = %(team_id)s AND {event_query}
                            AND toDateTime(events.timestamp) <= toDateTime(%(date_to)s) AND {trunc_func}(events.timestamp) >= toDateTime(%(date_from)s)
                            GROUP BY distinct_id
                        ) as e
                        CROSS JOIN (
                            SELECT toDateTime('0000-00-00 00:00:00') AS total, {trunc_func}(toDateTime(%(date_to)s) - number * %(seconds_in_interval)s) as day_start from numbers(%(num_intervals)s)
                        ) as b WHERE has(day, subsequent_day) = 0
                        ORDER BY distinct_id, subsequent_day ASC
                        ) WHERE
                        ((empty(neighbor(distinct_id, -1)) OR neighbor(distinct_id, -1) != distinct_id) AND subsequent_day != toDateTime(%(date_from)s))
                        OR
                        ( (neighbor(distinct_id, -1) = distinct_id) AND neighbor(subsequent_day, -1) < subsequent_day - INTERVAL {interval})
                    ) e
                JOIN (
                    SELECT DISTINCT distinct_id, {trunc_func}(min(events.timestamp)) earliest FROM events WHERE team_id = %(team_id)s AND event = %(event)s
                    GROUP BY distinct_id
                ) earliest ON e.distinct_id = earliest.distinct_id
            ) e
            JOIN
            (SELECT person_id,
                         distinct_id
                  FROM person_distinct_id
                  WHERE team_id = %(team_id)s) pdi on e.distinct_id = pdi.distinct_id
        )
        WHERE subsequent_day <= toDateTime(%(date_to)s) AND subsequent_day >= toDateTime(%(date_from)s)
        GROUP BY subsequent_day, status
    )
    GROUP BY day_start, status
    ORDER BY day_start ASC
)
GROUP BY status
"""
