PATH_BOUNCE_QUERY = """
SELECT
    counts.breakdown_value AS "context.columns.breakdown_value",
    tuple(counts.visitors, counts.previous_visitors) AS "context.columns.visitors",
    tuple(counts.views, counts.previous_views) AS "context.columns.views",
    tuple(bounce.bounce_rate, bounce.previous_bounce_rate) AS "context.columns.bounce_rate",
FROM (
    SELECT
        breakdown_value,
        uniqIf(filtered_person_id, {current_period}) AS visitors,
        uniqIf(filtered_person_id, {previous_period}) AS previous_visitors,
        sumIf(filtered_pageview_count, {current_period}) AS views,
        sumIf(filtered_pageview_count, {previous_period}) AS previous_views
    FROM (
        SELECT
            any(person_id) AS filtered_person_id,
            count() AS filtered_pageview_count,
            {breakdown_value} AS breakdown_value,
            session.session_id AS session_id,
            min(session.$start_timestamp) AS start_timestamp
        FROM events
        WHERE and(
            or(events.event == '$pageview', events.event == '$screen'),
            {inside_periods},
            {event_properties},
            {session_properties},
            {where_breakdown},
        )
        GROUP BY session_id, breakdown_value
    )
    GROUP BY breakdown_value
) as counts
LEFT JOIN (
    SELECT
        breakdown_value,
        avgIf(is_bounce, {current_period}) AS bounce_rate,
        avgIf(is_bounce, {previous_period}) AS previous_bounce_rate
    FROM (
        SELECT
            {bounce_breakdown_value} AS breakdown_value, -- use $entry_pathname to find the bounce rate for sessions that started on this pathname
            any(session.`$is_bounce`) AS is_bounce,
            session.session_id AS session_id,
            min(session.$start_timestamp) AS start_timestamp
        FROM events
        WHERE and(
            or(events.event == '$pageview', events.event == '$screen'),
            breakdown_value IS NOT NULL,
            {inside_periods},
            {bounce_event_properties}, -- Using filtered properties but excluding pathname
            {session_properties}
        )
        GROUP BY session_id, breakdown_value
    )
    GROUP BY breakdown_value
) as bounce
ON counts.breakdown_value = bounce.breakdown_value
"""

PATH_SCROLL_BOUNCE_QUERY = """
SELECT
    counts.breakdown_value AS "context.columns.breakdown_value",
    tuple(counts.visitors, counts.previous_visitors) AS "context.columns.visitors",
    tuple(counts.views, counts.previous_views) AS "context.columns.views",
    tuple(bounce.bounce_rate, bounce.previous_bounce_rate) AS "context.columns.bounce_rate",
    tuple(scroll.average_scroll_percentage, scroll.previous_average_scroll_percentage) AS "context.columns.average_scroll_percentage",
    tuple(scroll.scroll_gt80_percentage, scroll.previous_scroll_gt80_percentage) AS "context.columns.scroll_gt80_percentage",
FROM (
    SELECT
        breakdown_value,
        uniqIf(filtered_person_id, {current_period}) AS visitors,
        uniqIf(filtered_person_id, {previous_period}) AS previous_visitors,
        sumIf(filtered_pageview_count, {current_period}) AS views,
        sumIf(filtered_pageview_count, {previous_period}) AS previous_views
    FROM (
        SELECT
            any(person_id) AS filtered_person_id,
            count() AS filtered_pageview_count,
            {breakdown_value} AS breakdown_value,
            session.session_id AS session_id,
            min(session.$start_timestamp ) AS start_timestamp
        FROM events
        WHERE and(
            or(events.event == '$pageview', events.event == '$screen'),
            breakdown_value IS NOT NULL,
            {inside_periods},
            {event_properties},
            {session_properties},
        )
        GROUP BY session_id, breakdown_value
    )
    GROUP BY breakdown_value
) AS counts
LEFT JOIN (
    SELECT
        breakdown_value,
        avgIf(is_bounce, {current_period}) AS bounce_rate,
        avgIf(is_bounce, {previous_period}) AS previous_bounce_rate
    FROM (
        SELECT
            {bounce_breakdown_value} AS breakdown_value, -- use $entry_pathname to find the bounce rate for sessions that started on this pathname
            any(session.`$is_bounce`) AS is_bounce,
            session.session_id AS session_id,
            min(session.$start_timestamp) as start_timestamp
        FROM events
        WHERE and(
            or(events.event == '$pageview', events.event == '$screen'),
            breakdown_value IS NOT NULL,
            {inside_periods},
            {event_properties},
            {session_properties},
        )
        GROUP BY session_id, breakdown_value
    )
    GROUP BY breakdown_value
) AS bounce
ON counts.breakdown_value = bounce.breakdown_value
LEFT JOIN (
    SELECT
        breakdown_value,
        avgMergeIf(average_scroll_percentage_state, {current_period}) AS average_scroll_percentage,
        avgMergeIf(average_scroll_percentage_state, {previous_period}) AS previous_average_scroll_percentage,
        avgMergeIf(scroll_gt80_percentage_state, {current_period}) AS scroll_gt80_percentage,
        avgMergeIf(scroll_gt80_percentage_state, {previous_period}) AS previous_scroll_gt80_percentage
    FROM (
        SELECT
            {scroll_breakdown_value} AS breakdown_value, -- use $prev_pageview_pathname to find the scroll depth when leaving this pathname
            avgState(CASE
                WHEN toFloat(events.properties.`$prev_pageview_max_content_percentage`) IS NULL THEN NULL
                WHEN toFloat(events.properties.`$prev_pageview_max_content_percentage`) > 0.8 THEN 1
                ELSE 0
                END
            ) AS scroll_gt80_percentage_state,
            avgState(toFloat(events.properties.`$prev_pageview_max_scroll_percentage`)) as average_scroll_percentage_state,
            session.session_id AS session_id,
            min(session.$start_timestamp) AS start_timestamp
        FROM events
        WHERE and(
            or(events.event == '$pageview', events.event == '$pageleave', events.event == '$screen'),
            breakdown_value IS NOT NULL,
            {inside_periods},
            {event_properties_for_scroll},
            {session_properties},
        )
        GROUP BY session_id, breakdown_value
    )
    GROUP BY breakdown_value
) AS scroll
ON counts.breakdown_value = scroll.breakdown_value
"""

PATH_BOUNCE_AND_AVG_TIME_QUERY = """
SELECT
    counts.breakdown_value AS "context.columns.breakdown_value",

    tuple(counts.visitors, counts.previous_visitors) AS "context.columns.visitors",
    tuple(counts.views, counts.previous_views) AS "context.columns.views",

    tuple(
        coalesce(time_on_page.avg_time_on_page, 0),
        coalesce(time_on_page.previous_avg_time_on_page, 0)
    ) AS "context.columns.avg_time_on_page",

    tuple(
        coalesce(bounce.bounce_rate, 0),
        coalesce(bounce.previous_bounce_rate, 0)
    ) AS "context.columns.bounce_rate"

FROM (
    SELECT
        breakdown_value,
        uniqIf(filtered_person_id, {current_period}) AS visitors,
        uniqIf(filtered_person_id, {previous_period}) AS previous_visitors,
        sumIf(filtered_pageview_count, {current_period}) AS views,
        sumIf(filtered_pageview_count, {previous_period}) AS previous_views
    FROM (
        SELECT
            any(person_id) AS filtered_person_id,
            count() AS filtered_pageview_count,
            {breakdown_value} AS breakdown_value,
            session.session_id AS session_id,
            min(session.$start_timestamp) AS start_timestamp
        FROM events
        WHERE and(
            or(events.event = '$pageview', events.event = '$screen'),
            {inside_periods},
            {event_properties},
            {session_properties},
            {where_breakdown}
        )
        GROUP BY session_id, breakdown_value
    )
    GROUP BY breakdown_value
) AS counts

-- -----------------------------
-- Join: Avg Time on Page
-- -----------------------------
LEFT JOIN (
    SELECT
        {time_on_page_breakdown_value} AS breakdown_value,
        quantileIf(0.90)(
            least(toFloat(events.properties.`$prev_pageview_duration`), 86400),
            {avg_current_period}
        ) AS avg_time_on_page,
        quantileIf(0.90)(
            least(toFloat(events.properties.`$prev_pageview_duration`), 86400),
            {avg_previous_period}
        ) AS previous_avg_time_on_page
    FROM events
    WHERE and(
        or(events.event = '$pageview', events.event = '$pageleave', events.event = '$screen'),
        {time_on_page_breakdown_value} IS NOT NULL,
        events.properties.`$prev_pageview_duration` IS NOT NULL,
        {inside_periods},
        {time_on_page_event_properties},
        {session_properties}
    )
    GROUP BY breakdown_value
) AS time_on_page
ON counts.breakdown_value = time_on_page.breakdown_value

-- -----------------------------
-- Join: Bounce Rate
-- -----------------------------
LEFT JOIN (
    SELECT
        breakdown_value,
        avgIf(is_bounce, {current_period}) AS bounce_rate,
        avgIf(is_bounce, {previous_period}) AS previous_bounce_rate
    FROM (
        SELECT
            {bounce_breakdown_value} AS breakdown_value,
            any(session.`$is_bounce`) AS is_bounce,
            session.session_id AS session_id,
            min(session.$start_timestamp) AS start_timestamp
        FROM events
        WHERE and(
            or(events.event = '$pageview', events.event = '$screen'),
            breakdown_value IS NOT NULL,
            {inside_periods},
            {bounce_event_properties},
            {session_properties}
        )
        GROUP BY session_id, breakdown_value
    )
    GROUP BY breakdown_value
) AS bounce
ON counts.breakdown_value = bounce.breakdown_value
"""

FRUSTRATION_METRICS_INNER_QUERY = """
SELECT
    any(person_id) AS filtered_person_id,
    countIf(events.event = '$pageview' OR events.event = '$screen') AS filtered_pageview_count,
    {breakdown_value} AS breakdown_value,
    countIf(events.event = '$exception') AS errors_count,
    countIf(events.event = '$rageclick') AS rage_clicks_count,
    countIf(events.event = '$dead_click') AS dead_clicks_count,
    session.session_id AS session_id,
    min(session.$start_timestamp) as start_timestamp
FROM events
WHERE and({inside_periods}, {event_where}, {all_properties}, {where_breakdown})
GROUP BY session_id, breakdown_value
"""

MAIN_INNER_QUERY = """
SELECT
    any(person_id) AS filtered_person_id,
    count() AS filtered_pageview_count,
    {breakdown_value} AS breakdown_value,
    session.session_id AS session_id,
    any(session.$is_bounce) AS is_bounce,
    min(session.$start_timestamp) as start_timestamp
FROM events
WHERE and({inside_periods}, {event_where}, {all_properties}, {where_breakdown})
GROUP BY session_id, breakdown_value
"""
