_LIFECYCLE_EVENTS_QUERY = """
SELECT
    person_id,

    /*
        We want to put the status of each period onto it's own line, so we
        can easily aggregate over them. With the inner query we end up with a structure like:

        person_id  |  period_of_activity  | status_of_activity  | dormant_status_of_period_after_activity

        However, we want to have something of the format:

        person_id  | period_of_activity          |  status_of_activity
        person_id  | period_just_after_activity  |  dormant_status_of_period_after_activity

        such that we can simply aggregate over person_id, period.
    */
    arrayJoin(
        arrayZip(
            [period, period + INTERVAL 1 {interval_expr}],
            [initial_status, if(next_is_active, '', 'dormant')]
        )
    ) AS period_status_pairs,
    period_status_pairs.1 as start_of_period,
    period_status_pairs.2 as status
FROM (
    SELECT
        person_id,
        period,
        created_at,
        if(
            dateTrunc(%(interval)s, toDateTime(created_at, %(timezone)s)) = period,
            'new',
            if(
                previous_activity + INTERVAL 1 {interval_expr} = period,
                'returning',
                'resurrecting'
            )
        ) AS initial_status,
        period + INTERVAL 1 {interval_expr} = following_activity AS next_is_active,
        previous_activity,
        following_activity
    FROM (
        SELECT
            person_id,
            any(period) OVER (PARTITION BY person_id ORDER BY period ROWS BETWEEN 1 PRECEDING AND 1 PRECEDING) as previous_activity,
            period,
            any(period) OVER (PARTITION BY person_id ORDER BY period ROWS BETWEEN 1 FOLLOWING AND 1 FOLLOWING) as following_activity,
            created_at
        FROM ({events_query})
    )
)
WHERE period_status_pairs.2 != ''
SETTINGS allow_experimental_window_functions = 1
"""

LIFECYCLE_SQL = f"""
WITH
    %(interval)s AS selected_period,

    -- enumerate all requested periods, so we can zero fill as needed.
    -- NOTE: we use dateSub interval rather than seconds, which means we can handle,
    -- for instance, month intervals which do not have a fixed number of seconds.
    periods AS (
        SELECT dateSub(
            {{interval_expr}},
            number,
            dateTrunc(selected_period, toDateTime(%(date_to)s, %(timezone)s))
        ) AS start_of_period
        FROM numbers(
            dateDiff(
                %(interval)s,
                dateTrunc(%(interval)s, toDateTime(%(date_from)s)),
                dateTrunc(%(interval)s, toDateTime(%(date_to)s) + INTERVAL 1 {{interval_expr}})
            )
        )
    )
SELECT
    groupArray(start_of_period) as date,
    groupArray(counts) as data,
    status
FROM (
    SELECT if(
            status = 'dormant',
            toInt64(SUM(counts)) * toInt16(-1),
            toInt64(SUM(counts))
        ) as counts,
        start_of_period,
        status

    FROM (
        SELECT periods.start_of_period as start_of_period, toUInt16(0) AS counts, status

        FROM periods

        -- Zero fill for each status
        CROSS JOIN (
            SELECT status
            FROM (
                SELECT ['new', 'returning', 'resurrecting', 'dormant'] as status
            ) ARRAY JOIN status
        ) as sec
        ORDER BY status, start_of_period

        UNION ALL

        SELECT start_of_period, count(DISTINCT person_id) counts, status
        FROM ({_LIFECYCLE_EVENTS_QUERY})
        WHERE start_of_period <= dateTrunc(%(interval)s, toDateTime(%(date_to)s, %(timezone)s))
          AND start_of_period >= dateTrunc(%(interval)s, toDateTime(%(date_from)s, %(timezone)s))
        GROUP BY start_of_period, status
    )
    GROUP BY start_of_period, status
    ORDER BY start_of_period ASC
)
GROUP BY status
"""

LIFECYCLE_PEOPLE_SQL = f"""
SELECT person_id
FROM ({_LIFECYCLE_EVENTS_QUERY}) e
WHERE status = %(status)s
AND dateTrunc(%(interval)s, toDateTime(%(target_date)s, %(timezone)s)) = start_of_period
LIMIT %(limit)s OFFSET %(offset)s
"""
