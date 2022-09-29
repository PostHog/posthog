PATH_ARRAY_QUERY = """
    SELECT person_id,
            path,
            {extra_final_select_statements}
            conversion_time,
            event_in_session_index,
            concat(toString(event_in_session_index), '_', path) as path_key,
            if(event_in_session_index > 1, concat(toString(event_in_session_index-1), '_', prev_path), null) AS last_path_key,
            path_dropoff_key
        FROM (

            SELECT person_id
                , joined_path_tuple.1 as path
                , joined_path_tuple.2 as conversion_time
                , joined_path_tuple.3 as prev_path
                , event_in_session_index
                , session_index
                , arrayPopFront(arrayPushBack(path_basic, '')) as path_basic_0
                , arrayMap((x,y) -> if(x=y, 0, 1), path_basic, path_basic_0) as mapping
                , arrayFilter((x,y) -> y, time, mapping) as timings
                , arrayFilter((x,y)->y, path_basic, mapping) as compact_path
                {extra_joined_path_tuple_select_statements}
                {extra_array_filter_select_statements}
                {target_clause}
                , arrayDifference(limited_timings) as timings_diff
                , arrayZip(limited_path, timings_diff, arrayPopBack(arrayPushFront(limited_path, '')) {extra_limited_path_tuple_elements}) as limited_path_timings
                , concat(toString(length(limited_path)), '_', limited_path[-1]) as path_dropoff_key /* last path item */
            FROM (
                SELECT person_id
                    , path_time_tuple.1 as path_basic
                    , path_time_tuple.2 as time
                    {extra_path_time_tuple_select_statements}
                    , session_index
                    , arrayZip(paths, timing, arrayDifference(timing) {extra_paths_tuple_elements}) as paths_tuple
                    , {session_threshold_clause} as session_paths
                FROM (
                        SELECT person_id,
                                groupArray(toUnixTimestamp64Milli(timestamp)) as timing,
                                {extra_group_array_select_statements}
                                groupArray(path_item) as paths
                        FROM ({path_event_query})
                        GROUP BY person_id
                        )
                /* this array join splits paths for a single personID per session */
                ARRAY JOIN session_paths AS path_time_tuple, arrayEnumerate(session_paths) AS session_index
            )
            ARRAY JOIN limited_path_timings AS joined_path_tuple, arrayEnumerate(limited_path_timings) AS event_in_session_index
            {boundary_event_filter}
            )
"""
