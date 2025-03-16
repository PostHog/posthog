/* user_id:151340 celery:posthog.tasks.tasks.process_query_task */ SELECT
    sum(step_1) AS step_1,
    sum(step_2) AS step_2,
    arrayMap(x -> if(isNaN(x), NULL, x), [avgArrayOrNull(step_1_conversion_times)])[1] AS step_1_average_conversion_time,
    arrayMap(x -> if(isNaN(x), NULL, x), [medianArrayOrNull(step_1_conversion_times)])[1] AS step_1_median_conversion_time,
    groupArray(row_number) AS row_number,
    final_prop AS final_prop
FROM
    (SELECT
        countIf(ifNull(ifNull(equals(step_reached, 0), 0), 0)) AS step_1,
        countIf(ifNull(ifNull(equals(step_reached, 1), 0), 0)) AS step_2,
        groupArrayIf(timings[1], ifNull(greater(timings[1], 0), 0)) AS step_1_conversion_times,
        rowNumberInAllBlocks() AS row_number,
        if(ifNull(less(row_number, 25), 0), breakdown, ['Other']) AS final_prop
    FROM
        (SELECT
            arraySort(t -> t.1, groupArray(tuple(accurateCastOrNull(timestamp, 'Float64'), uuid, prop, arrayFilter(x -> ifNull(notEquals(x, 0), 1), [multiply(1, step_0), multiply(2, step_1)])))) AS events_array,
            arrayJoin(aggregate_funnel_array_v4(2, 86400, 'all_events', 'ordered', groupUniqArrayIf(prop, ifNull(notEquals(prop, []), isNotNull(prop) or isNotNull([]))), arrayFilter((x, x_before, x_after) -> not(and(ifNull(lessOrEquals(length(x.4), 1), 0), ifNull(equals(x.4, x_before.4), isNull(x.4) and isNull(x_before.4)), ifNull(equals(x.4, x_after.4), isNull(x.4) and isNull(x_after.4)), ifNull(equals(x.3, x_before.3), isNull(x.3) and isNull(x_before.3)), ifNull(equals(x.3, x_after.3), isNull(x.3) and isNull(x_after.3)), ifNull(greater(x.1, x_before.1), 0), ifNull(less(x.1, x_after.1), 0))), events_array, arrayRotateRight(events_array, 1), arrayRotateLeft(events_array, 1)))) AS af_tuple,
            af_tuple.1 AS step_reached,
            plus(af_tuple.1, 1) AS steps,
            af_tuple.2 AS breakdown,
            af_tuple.3 AS timings,
            aggregation_target AS aggregation_target
        FROM
            (SELECT
                toTimeZone(e.timestamp, 'America/New_York') AS timestamp,
                if(not(empty(e__override.distinct_id)), e__override.person_id, e.person_id) AS aggregation_target,
                e.uuid AS uuid,
                e.`$session_id` AS `$session_id`,
                e.`$window_id` AS `$window_id`,
                if(and(equals(e.event, 'page_view'), and(ifNull(equals(nullIf(nullIf(e.mat_page, ''), 'null'), 'menu'), 0), ifNull(equals(nullIf(nullIf(e.`mat_$geoip_country_code`, ''), 'null'), 'US'), 0), or(equals(e.properties_group_feature_flags['$feature/restaurant-theme'], 'control'), equals(e.properties_group_feature_flags['$feature/restaurant-theme'], 'test')))), 1, 0) AS step_0,
                if(equals(e.event, 'purchase'), 1, 0) AS step_1,
                [ifNull(toString(has(e.properties_group_feature_flags, '$feature/restaurant-theme') ? e.properties_group_feature_flags['$feature/restaurant-theme'] : null), '')] AS prop_basic,
                prop_basic AS prop
            FROM
                events AS e
                LEFT OUTER JOIN (SELECT
                    argMax(person_distinct_id_overrides.person_id, person_distinct_id_overrides.version) AS person_id,
                    person_distinct_id_overrides.distinct_id AS distinct_id
                FROM
                    person_distinct_id_overrides
                WHERE
                    equals(person_distinct_id_overrides.team_id, 91996)
                GROUP BY
                    person_distinct_id_overrides.distinct_id
                HAVING
                    ifNull(equals(argMax(person_distinct_id_overrides.is_deleted, person_distinct_id_overrides.version), 0), 0)
                SETTINGS optimize_aggregation_in_order=1) AS e__override ON equals(e.distinct_id, e__override.distinct_id)
            WHERE
                and(equals(e.team_id, 91996), and(and(greaterOrEquals(toTimeZone(e.timestamp, 'America/New_York'), toDateTime64('2025-03-05 14:14:48.742000', 6, 'America/New_York')), lessOrEquals(toTimeZone(e.timestamp, 'America/New_York'), toDateTime64('2025-03-09 08:42:02.096104', 6, 'America/New_York'))), in(e.event, tuple('page_view', 'purchase')), ifNull(not(match(toString(nullIf(nullIf(e.`mat_$host`, ''), 'null')), '^(localhost|127\\.0\\.0\\.1)($|:)')), 1)), or(ifNull(equals(step_0, 1), 0), ifNull(equals(step_1, 1), 0))))
        GROUP BY
            aggregation_target
        HAVING
            ifNull(greaterOrEquals(step_reached, 0), 0))
    GROUP BY
        breakdown
    ORDER BY
        step_2 DESC,
        step_1 DESC)
GROUP BY
    final_prop
LIMIT 26 SETTINGS join_algorithm='auto', readonly=2, max_execution_time=600, allow_experimental_object_type=1, format_csv_allow_double_quotes=0, max_ast_elements=4000000, max_expanded_ast_elements=4000000, max_bytes_before_external_group_by=23622320128, allow_experimental_analyzer=1