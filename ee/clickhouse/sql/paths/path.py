# Step 1. Make a table with the following fields from events:
#
# - person_id = dedupe event distinct_ids into person_id
# - timestamp
# - path_type = either name of event or $current_url or ...
# - new_session = this is 1 when the event is from a new session
#                 or 0 if it's less than 30min after and for the same person_id as the previous event
# - marked_session_start = this is the same as "new_session" if no start point given, otherwise it's 1 if
#                          the current event is the start point (e.g. path_start=/about) or 0 otherwise
paths_query_step_1 = """
    SELECT
        person_id,
        timestamp,
        event_id,
        path_type,
        neighbor(person_id, -1) != person_id OR dateDiff('minute', toDateTime(neighbor(timestamp, -1)), toDateTime(timestamp)) > 30 AS new_session,
        {marked_session_start} as marked_session_start
    FROM (
        SELECT
            timestamp,
            person_id,
            events.uuid AS event_id,
            {path_type} AS path_type
            {select_elements_chain}
        FROM events AS events
        JOIN ({GET_TEAM_PERSON_DISTINCT_IDS}) as person_distinct_id ON person_distinct_id.distinct_id = events.distinct_id
        WHERE
            events.team_id = %(team_id)s
            AND {event_query}
            {filters}
            {parsed_date_from}
            {parsed_date_to}
        GROUP BY
            person_id,
            timestamp,
            event_id,
            path_type
            {group_by_elements_chain}
        ORDER BY
            person_id,
            timestamp
    )
    WHERE {excess_row_filter}
"""

# Step 2.
# - Convert new_session = {1 or 0} into
#      ---> session_id = {1, 2, 3...}
# - Remove all "marked_session_start = 0" rows at the start of a session
paths_query_step_2 = """
    SELECT 
        person_id,
        event_id,
        timestamp,
        path_type,
        runningAccumulate(session_id_sumstate) as session_id
    FROM (
        SELECT 
            *,
            sumState(new_session) AS session_id_sumstate
        FROM 
            ({paths_query})
        GROUP BY
            person_id,
            timestamp,
            event_id,
            path_type,
            new_session,
            marked_session_start
        ORDER BY 
            person_id, 
            timestamp
    )
    WHERE
        marked_session_start = 1 or
        (neighbor(marked_session_start, -1) = 1 and neighbor(session_id, -1) = session_id) or
        (neighbor(marked_session_start, -2) = 1 and neighbor(session_id, -2) = session_id) or
        (neighbor(marked_session_start, -3) = 1 and neighbor(session_id, -3) = session_id)
""".format(
    paths_query=paths_query_step_1
)

# Step 3.
# - Add event index per session
# - Use the index and path_type to create a path key (e.g. "1_/pricing", "2_/help")
# - Remove every unused row per session (5th and later rows)
#   Those rows will only be there if many filter.start_point rows are in a query.
#   For example start_point=/pricing and the user clicked back and forth between pricing and other pages.
paths_query_step_3 = """
    SELECT
        person_id,
        event_id,
        timestamp,
        path_type,
        session_id,
        (neighbor(session_id, -4) = session_id ? 5 :
        (neighbor(session_id, -3) = session_id ? 4 :
        (neighbor(session_id, -2) = session_id ? 3 :
        (neighbor(session_id, -1) = session_id ? 2 : 1)))) as session_index,
        concat(toString(session_index), '_', path_type) as path_key,
        if(session_index > 1, neighbor(path_key, -1), null) AS last_path_key,
        if(session_index > 1, neighbor(event_id, -1), null) AS last_event_id
    FROM ({paths_query})
    WHERE
        session_index <= 4
""".format(
    paths_query=paths_query_step_2
)

# Step 4.
# - Aggregate and get counts for unique pairs
# - Filter out the entry rows that come from "null"
PATHS_QUERY_FINAL = """
    SELECT 
        last_path_key as source_event,
        any(last_event_id) as source_event_id,
        path_key as target_event,
        any(event_id) target_event_id, 
        COUNT(*) AS event_count
    FROM (
        {paths_query}
    )
    WHERE 
        source_event IS NOT NULL
        AND target_event IS NOT NULL
    GROUP BY
        source_event,
        target_event
    ORDER BY
        event_count DESC,
        source_event,
        target_event
    LIMIT 20
""".format(
    paths_query=paths_query_step_3
)


PATH_ARRAY_QUERY = """
SELECT last_path_key as source_event,
       path_key as target_event,
       COUNT(*) AS event_count,
       avg(conversion_time) AS average_conversion_time
  FROM (
        SELECT person_id,
               path,
               conversion_time,
               event_in_session_index,
               concat(toString(event_in_session_index), '_', path) as path_key,
               if(event_in_session_index > 1, neighbor(path_key, -1), null) AS last_path_key
          FROM (
          
              SELECT person_id
                    , joined_path_tuple.1 as path
                    , joined_path_tuple.2 as conversion_time
                    , event_in_session_index
                    , session_index
                    , arrayPopFront(arrayPushBack(path_basic, '')) as path_basic_0
                    , arrayMap((x,y) -> if(x=y, 0, 1), path_basic, path_basic_0) as mapping
                    , arrayFilter((x,y) -> y, time, mapping) as timings
                    , arrayFilter((x,y)->y, path_basic, mapping) as compact_path
                    {target_clause}
                    , arrayDifference(limited_timings) as timings_diff
                    , arrayZip(limited_path, timings_diff) as limited_path_timings
                FROM (
                    SELECT person_id
                        , path_time_tuple.1 as path_basic
                        , path_time_tuple.2 as time
                        , session_index
                        , arrayZip(paths, timing, arrayDifference(timing)) as paths_tuple
                        , arraySplit(x -> if(x.3 < %(session_time_threshold)s, 0, 1), paths_tuple) as session_paths
                    FROM (
                            SELECT person_id,
                                   groupArray(toUnixTimestamp64Milli(timestamp)) as timing,
                                   groupArray(path_item) as paths
                            FROM ({path_event_query})
                            GROUP BY person_id
                            ORDER BY person_id
                           )
                    /* this array join splits paths for a single personID per session */
                    ARRAY JOIN session_paths AS path_time_tuple, arrayEnumerate(session_paths) AS session_index
                )
                ARRAY JOIN limited_path_timings AS joined_path_tuple, arrayEnumerate(limited_path_timings) AS event_in_session_index
                {boundary_event_filter}
                ORDER BY person_id, session_index, event_in_session_index
               )
       )
 WHERE source_event IS NOT NULL
 GROUP BY source_event,
          target_event
 ORDER BY event_count DESC,
          source_event,
          target_event
 LIMIT 20

"""
