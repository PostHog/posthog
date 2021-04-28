SESSIONS_NO_EVENTS_SQL = """
SELECT
    session_duration_seconds,
    timestamp
FROM
(
    SELECT
        is_new_session,
        is_end_session,
        if(is_end_session AND is_new_session, 0, if(is_new_session AND (NOT is_end_session), dateDiff('second', toDateTime(timestamp), toDateTime(neighbor(timestamp, 1))), NULL)) AS session_duration_seconds,
        timestamp
    FROM
    (
        SELECT
            timestamp,
            neighbor(distinct_id, -1) AS start_possible_neighbor,
            neighbor(timestamp, -1) AS start_possible_prev_ts,
            if((start_possible_neighbor != distinct_id) OR (dateDiff('minute', toDateTime(start_possible_prev_ts), toDateTime(timestamp)) > 30), 1, 0) AS is_new_session,
            neighbor(distinct_id, 1) AS end_possible_neighbor,
            neighbor(timestamp, 1) AS end_possible_prev_ts,
            if((end_possible_neighbor != distinct_id) OR (dateDiff('minute', toDateTime(timestamp), toDateTime(end_possible_prev_ts)) > 30), 1, 0) AS is_end_session
        FROM
        (
            SELECT
                timestamp,
                distinct_id
            FROM events
            WHERE 
                team_id = %(team_id)s
                {entity_filter}
                {date_from}
                {date_to} 
                {filters}
            GROUP BY
                timestamp,
                distinct_id
            ORDER BY
                distinct_id ASC,
                timestamp ASC
        )
    )
    WHERE (is_new_session AND (NOT is_end_session)) OR (is_end_session AND (NOT is_new_session)) OR (is_end_session AND is_new_session)
)
WHERE is_new_session
{sessions_limit}
"""
