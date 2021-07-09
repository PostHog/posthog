SESSIONS_DISTINCT_ID_SQL = """
    SELECT distinct distinct_id
    FROM
        events
    WHERE team_id = %(team_id)s
    {date_from}
    {date_to}
    {person_filters}
    {action_filters}
    ORDER BY timestamp DESC
    LIMIT %(distinct_id_limit)s
"""

SESSION_SQL = """
    SELECT
        distinct_id,
        gid,
        dateDiff('second', toDateTime(arrayReduce('min', groupArray(timestamp))), toDateTime(arrayReduce('max', groupArray(timestamp)))) AS elapsed,
        arrayReduce('min', groupArray(timestamp)) as start_time,
        arrayReduce('max', groupArray(timestamp)) as end_time,
        JSONExtractString(arrayElement(groupArray(properties), 1), '$current_url') as start_url,
        JSONExtractString(arrayElement(groupArray(properties), -1), '$current_url') as end_url
        {filters_select_clause}
    FROM (
        SELECT
            distinct_id,
            event,
            timestamp,
            uuid,
            properties,
            elements_chain,
            arraySum(arraySlice(gids, 1, idx)) AS gid
            {matches_action_clauses}
        FROM (
            SELECT
                groupArray(timestamp) as timestamps,
                groupArray(event) as events,
                groupArray(uuid) as uuids,
                groupArray(properties) as property_list,
                groupArray(elements_chain) as elements_chains,
                groupArray(distinct_id) as distinct_ids,
                groupArray(new_session) AS gids
            FROM (
                SELECT
                    distinct_id,
                    uuid,
                    event,
                    properties,
                    elements_chain,
                    timestamp,
                    neighbor(distinct_id, -1) as possible_neighbor,
                    neighbor(timestamp, -1) as possible_prev,
                    if(possible_neighbor != distinct_id or dateDiff('minute', toDateTime(possible_prev), toDateTime(timestamp)) > 30, 1, 0) as new_session
                FROM (
                    SELECT
                        uuid,
                        event,
                        properties,
                        timestamp,
                        distinct_id,
                        elements_chain
                    FROM
                        events
                    WHERE
                        team_id = %(team_id)s
                        AND event != '$feature_flag_called'
                        {date_from}
                        {date_to}
                        AND distinct_id IN %(distinct_ids)s
                    GROUP BY
                        uuid,
                        event,
                        properties,
                        timestamp,
                        distinct_id,
                        elements_chain
                    ORDER BY
                        distinct_id,
                        timestamp
                )
            )
        )
        ARRAY JOIN
            distinct_ids as distinct_id,
            events as event,
            timestamps as timestamp,
            uuids as uuid,
            property_list as properties,
            elements_chains as elements_chain,
            arrayEnumerate(gids) AS idx
    )
    GROUP BY
        distinct_id,
        gid
    {filters_having}
    ORDER BY
        end_time DESC
    {sessions_limit}
"""

SESSION_EVENTS = """
SELECT
    uuid,
    event,
    properties,
    timestamp,
    elements_chain
FROM events
WHERE team_id = %(team_id)s
  AND event != '$feature_flag_called'
  AND distinct_id = %(distinct_id)s
  {date_from}
  {date_to}
ORDER BY timestamp
"""
