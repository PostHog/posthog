PATH_ARRAY_QUERY = """
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

"""
