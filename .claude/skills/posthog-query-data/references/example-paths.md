# User paths (pageviews, three steps, applied path cleaning and filters, maximum 50 paths)

```sql
SELECT
    last_path_key AS source_event,
    path_key AS target_event,
    COUNT(*) AS event_count,
    avg(conversion_time) AS average_conversion_time
FROM
    (SELECT
        person_id,
        path,
        conversion_time,
        event_in_session_index,
        concat(toString(event_in_session_index), '_', path) AS path_key,
        if(greater(event_in_session_index, 1), concat(toString(minus(event_in_session_index, 1)), '_', prev_path), NULL) AS last_path_key,
        path_dropoff_key
    FROM
        (SELECT
            person_id,
            joined_path_tuple.1 AS path,
            joined_path_tuple.2 AS conversion_time,
            joined_path_tuple.3 AS prev_path,
            event_in_session_index,
            session_index,
            arrayPopFront(arrayPushBack(path_basic, '')) AS path_basic_0,
            arrayMap((x, y) -> if(equals(x, y), 0, 1), path_basic, path_basic_0) AS mapping,
            arrayFilter((x, y) -> y, time, mapping) AS timings,
            arrayFilter((x, y) -> y, path_basic, mapping) AS compact_path,
            indexOf(compact_path, NULL) AS target_index,
            if(greater(target_index, 0), arraySlice(compact_path, target_index), compact_path) AS filtered_path,
            arraySlice(filtered_path, 1, 3) AS limited_path,
            if(greater(target_index, 0), arraySlice(timings, target_index), timings) AS filtered_timings,
            arraySlice(filtered_timings, 1, 3) AS limited_timings,
            arrayDifference(limited_timings) AS timings_diff,
            concat(toString(length(limited_path)), '_', limited_path[-1]) AS path_dropoff_key,
            arrayZip(limited_path, timings_diff, arrayPopBack(arrayPushFront(limited_path, ''))) AS limited_path_timings
        FROM
            (SELECT
                person_id,
                path_time_tuple.1 AS path_basic,
                path_time_tuple.2 AS time,
                session_index,
                arrayZip(path_list, timing_list, arrayDifference(timing_list)) AS paths_tuple,
                arraySplit(x -> if(less(x.3, 1800), 0, 1), paths_tuple) AS session_paths
            FROM
                (SELECT
                    person_id,
                    groupArray(timestamp) AS timing_list,
                    groupArray(path_item) AS path_list
                FROM
                    (SELECT
                        events.timestamp,
                        events.person_id,
                        ifNull(if(equals(event, '$pageview'), replaceRegexpAll(ifNull(properties.$current_url, ''), '(.)/$', '\\1'), event), '') AS path_item_ungrouped,
                        replaceRegexpAll(path_item_ungrouped, '^https:\\/\\/[a-z-]+\\.posthog\\.com', 'https://<region>.posthog.com') AS path_item_0,
                        replaceRegexpAll(path_item_0, '\\/project\\/\\d+', '/project/<team_id>') AS path_item_1,
                        replaceRegexpAll(path_item_1, '\\/llm-analytics\\/traces\\/[0-9a-f\\-]+', '/llm-analytics/traces/<trace_id>') AS path_item_2,
                        replaceRegexpAll(path_item_2, '\\/llm-analytics\\/sessions\\/[0-9a-f\\-]+', '/llm-analytics/sessions/<session_id>') AS path_item_3,
                        replaceRegexpAll(path_item_3, '\\/llm-analytics\\/evaluations\\/[0-9a-f\\-]+', '/llm-analytics/evaluations/<evaluation_id>') AS path_item_4,
                        replaceRegexpAll(path_item_4, '\\/llm-analytics\\/datasets\\/[0-9a-f\\-]+', '/llm-analytics/datasets/<dataset_id>') AS path_item_cleaned,
                        NULL AS groupings,
                        multiMatchAnyIndex(path_item_cleaned, NULL) AS group_index,
                        (if(greater(group_index, 0), groupings[group_index], path_item_cleaned) AS path_item) AS path_item
                    FROM
                        events
                    WHERE
                        and(and(ilike(toString(properties.$pathname), '%llm-analytics%'), notILike(toString(properties.$pathname), '%docs%')), and(greaterOrEquals(events.timestamp, toStartOfInterval(assumeNotNull(toDateTime('2026-01-20 00:00:00')), toIntervalDay(1))), lessOrEquals(events.timestamp, assumeNotNull(toDateTime('2026-01-27 23:59:59')))), equals(event, '$pageview'))
                    ORDER BY
                        person_id ASC,
                        events.timestamp ASC)
                GROUP BY
                    person_id)
            ARRAY JOIN session_paths AS path_time_tuple, arrayEnumerate(session_paths) AS session_index)
        ARRAY JOIN limited_path_timings AS joined_path_tuple, arrayEnumerate(limited_path_timings) AS event_in_session_index))
WHERE
    notEquals(source_event, NULL)
GROUP BY
    source_event,
    target_event
ORDER BY
    event_count DESC,
    source_event ASC,
    target_event ASC
LIMIT 50
```
