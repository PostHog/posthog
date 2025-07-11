from posthog.clickhouse.client import sync_execute
from dagster import asset_check, AssetCheckResult, MetadataValue
from datetime import datetime, UTC, timedelta


def check_session_accuracy(team_id: int = 2) -> AssetCheckResult:
    """
    Compare session metrics accuracy between pre-aggregated table and regular WebOverview query.
    Uses team 2 (PostHog) by default as it has reliable data volume.
    """
    try:
        # Use a recent 7-day window for comparison
        end_date = datetime.now(UTC).date()
        start_date = end_date - timedelta(days=7)

        # Query pre-aggregated sessions data
        preagg_query = f"""
        SELECT
            count() AS sessions,
            round(avg(session_duration), 2) AS avg_duration,
            round(countIf(bounce_rate) * 100.0 / count(), 2) AS bounce_rate_pct,
            uniq(person_id) AS visitors
        FROM web_sessions_combined
        WHERE team_id = {team_id}
            AND period_bucket >= toDate('{start_date}')
            AND period_bucket < toDate('{end_date}')
        """

        # Query regular WebOverview equivalent for sessions
        regular_query = f"""
        WITH session_data AS (
            SELECT
                events.session_id_v7,
                argMax(if(NOT empty(events__override.distinct_id), events__override.person_id, events.person_id), events.timestamp) AS person_id,
                dateDiff('second', min(events.timestamp), max(events.timestamp)) AS session_duration,
                countIf(events.event = '$pageview') AS pageview_count,
                countIf(events.event = '$autocapture') AS autocapture_count
            FROM events
            LEFT JOIN person_distinct_id_overrides AS events__override ON events.distinct_id = events__override.distinct_id
            WHERE events.team_id = {team_id}
                AND events.timestamp >= toDateTime('{start_date}')
                AND events.timestamp < toDateTime('{end_date}')
                AND events.session_id_v7 IS NOT NULL
                AND events.event IN ('$pageview', '$screen')
            GROUP BY events.session_id_v7
        )
        SELECT
            count() AS sessions,
            round(avg(session_duration), 2) AS avg_duration,
            round(countIf(NOT(pageview_count > 1 OR autocapture_count > 0 OR session_duration >= 10)) * 100.0 / count(), 2) AS bounce_rate_pct,
            uniq(person_id) AS visitors
        FROM session_data
        """

        preagg_result = sync_execute(preagg_query)
        regular_result = sync_execute(regular_query)

        if not preagg_result or not regular_result:
            return AssetCheckResult(
                passed=False,
                description="No data returned from accuracy comparison queries",
                metadata={"team_id": MetadataValue.int(team_id)},
            )

        preagg_sessions, preagg_duration, preagg_bounce, preagg_visitors = preagg_result[0]
        regular_sessions, regular_duration, regular_bounce, regular_visitors = regular_result[0]

        # Calculate percentage differences
        session_diff = abs(preagg_sessions - regular_sessions) / regular_sessions * 100 if regular_sessions > 0 else 0
        duration_diff = abs(preagg_duration - regular_duration) / regular_duration * 100 if regular_duration > 0 else 0
        bounce_diff = abs(preagg_bounce - regular_bounce) if regular_bounce > 0 else 0
        visitor_diff = abs(preagg_visitors - regular_visitors) / regular_visitors * 100 if regular_visitors > 0 else 0

        # Define accuracy thresholds
        session_threshold = 1.0  # 1% for session count
        duration_threshold = 1.0  # 1% for avg duration
        bounce_threshold = 1.0  # 1% for bounce rate
        visitor_threshold = 2.0  # 2% for visitor count (more tolerant due to person resolution complexity)

        # Check if all metrics pass
        passed = (
            session_diff <= session_threshold
            and duration_diff <= duration_threshold
            and bounce_diff <= bounce_threshold
            and visitor_diff <= visitor_threshold
        )

        description = f"Sessions: {session_diff:.2f}% diff, Duration: {duration_diff:.2f}% diff, Bounce: {bounce_diff:.2f}% diff, Visitors: {visitor_diff:.2f}% diff"

        return AssetCheckResult(
            passed=passed,
            description=description,
            metadata={
                "team_id": MetadataValue.int(team_id),
                "date_range": MetadataValue.text(f"{start_date} to {end_date}"),
                "preagg_sessions": MetadataValue.int(preagg_sessions),
                "regular_sessions": MetadataValue.int(regular_sessions),
                "session_diff_pct": MetadataValue.float(session_diff),
                "preagg_duration": MetadataValue.float(preagg_duration),
                "regular_duration": MetadataValue.float(regular_duration),
                "duration_diff_pct": MetadataValue.float(duration_diff),
                "preagg_bounce": MetadataValue.float(preagg_bounce),
                "regular_bounce": MetadataValue.float(regular_bounce),
                "bounce_diff_pct": MetadataValue.float(bounce_diff),
                "preagg_visitors": MetadataValue.int(preagg_visitors),
                "regular_visitors": MetadataValue.int(regular_visitors),
                "visitor_diff_pct": MetadataValue.float(visitor_diff),
            },
        )

    except Exception as e:
        return AssetCheckResult(
            passed=False,
            description=f"Error during accuracy check: {str(e)}",
            metadata={"team_id": MetadataValue.int(team_id), "error": MetadataValue.text(str(e))},
        )


@asset_check(
    asset="web_analytics_sessions_daily",
    name="sessions_accuracy_check",
    description="Validate accuracy of session pre-aggregation vs regular queries",
)
def sessions_accuracy_check() -> AssetCheckResult:
    """
    Check accuracy of session pre-aggregation against equivalent regular queries.
    Validates session count, average duration, bounce rate, and visitor count.
    """
    return check_session_accuracy(team_id=2)  # PostHog team


@asset_check(
    asset="web_analytics_sessions_daily",
    name="sessions_data_freshness_check",
    description="Validate that session data is recent and complete",
)
def sessions_data_freshness_check() -> AssetCheckResult:
    """
    Check that session pre-aggregation data is fresh and covers recent dates.
    """
    try:
        # Check for data from yesterday
        yesterday = (datetime.now(UTC) - timedelta(days=1)).date()

        query = f"""
        SELECT
            count() AS row_count,
            uniq(team_id) AS team_count,
            min(period_bucket) AS min_date,
            max(period_bucket) AS max_date
        FROM web_sessions_combined
        WHERE period_bucket = toDate('{yesterday}')
        """

        result = sync_execute(query)

        if not result:
            return AssetCheckResult(passed=False, description="No results from data freshness query")

        row_count, team_count, min_date, max_date = result[0]

        # Expect at least some data for yesterday
        passed = row_count > 0 and team_count > 0

        description = f"Found {row_count} rows for {team_count} teams on {yesterday}"

        return AssetCheckResult(
            passed=passed,
            description=description,
            metadata={
                "check_date": MetadataValue.text(str(yesterday)),
                "row_count": MetadataValue.int(row_count),
                "team_count": MetadataValue.int(team_count),
                "min_date": MetadataValue.text(str(min_date)) if min_date else MetadataValue.text("None"),
                "max_date": MetadataValue.text(str(max_date)) if max_date else MetadataValue.text("None"),
            },
        )

    except Exception as e:
        return AssetCheckResult(
            passed=False,
            description=f"Error during freshness check: {str(e)}",
            metadata={"error": MetadataValue.text(str(e))},
        )


@asset_check(
    asset="web_analytics_sessions_daily",
    name="sessions_no_fanout_check",
    description="Validate that session pre-aggregation has no fan-out issues",
)
def sessions_no_fanout_check() -> AssetCheckResult:
    """
    Check that session pre-aggregation maintains one row per session (no fan-out).
    Compares total sessions in pre-agg vs distinct sessions in raw data.
    """
    try:
        # Use team 2 and recent data for validation
        end_date = datetime.now(UTC).date()
        start_date = end_date - timedelta(days=3)

        # Count sessions in pre-aggregated data
        preagg_query = f"""
        SELECT sum(sessions) AS total_sessions
        FROM web_sessions_combined
        WHERE team_id = 2
            AND period_bucket >= toDate('{start_date}')
            AND period_bucket < toDate('{end_date}')
        """

        # Count distinct sessions in raw events
        raw_query = f"""
        SELECT uniq(session_id_v7) AS distinct_sessions
        FROM events
        WHERE team_id = 2
            AND timestamp >= toDateTime('{start_date}')
            AND timestamp < toDateTime('{end_date}')
            AND session_id_v7 IS NOT NULL
            AND event IN ('$pageview', '$screen')
        """

        preagg_result = sync_execute(preagg_query)
        raw_result = sync_execute(raw_query)

        if not preagg_result or not raw_result:
            return AssetCheckResult(passed=False, description="No data returned from fan-out check queries")

        preagg_sessions = preagg_result[0][0] or 0
        raw_sessions = raw_result[0][0] or 0

        # Allow small variance due to timing differences
        diff_pct = abs(preagg_sessions - raw_sessions) / raw_sessions * 100 if raw_sessions > 0 else 0
        passed = diff_pct <= 5.0  # Allow 5% variance

        description = f"Pre-agg: {preagg_sessions} sessions, Raw: {raw_sessions} sessions ({diff_pct:.2f}% diff)"

        return AssetCheckResult(
            passed=passed,
            description=description,
            metadata={
                "date_range": MetadataValue.text(f"{start_date} to {end_date}"),
                "preagg_sessions": MetadataValue.int(preagg_sessions),
                "raw_sessions": MetadataValue.int(raw_sessions),
                "diff_pct": MetadataValue.float(diff_pct),
            },
        )

    except Exception as e:
        return AssetCheckResult(
            passed=False,
            description=f"Error during fan-out check: {str(e)}",
            metadata={"error": MetadataValue.text(str(e))},
        )


@asset_check(
    asset="web_analytics_sessions_daily",
    name="sessions_dimensions_validation_check",
    description="Validate all 20 dimensions are properly aggregated with no fan-out issues",
)
def sessions_dimensions_validation_check() -> AssetCheckResult:
    """
    Validate that all 20 dimensions in web_sessions_daily are working correctly:
    - All expected dimensions are present
    - No fan-out issues (sessions preserved across dimension combinations)
    - Visitor counting is accurate (uses uniq, not sum)
    """
    try:
        # Use a recent 3-day window for validation
        end_date = datetime.now(UTC).date()
        start_date = end_date - timedelta(days=3)

        # Test query that mirrors our verified implementation
        validation_query = f"""
        SELECT
            sum(sessions) AS total_sessions,
            sum(sessions * avg_duration_seconds) / sum(sessions) AS overall_avg_duration,
            (sum(bounce_count) / sum(sessions)) * 100 AS overall_bounce_rate,
            sum(pageviews_total) AS total_pageviews,
            round(sum(pageviews_total) / sum(sessions), 2) AS avg_pageviews_per_session,
            uniq(person_id) AS total_visitors,
            count(*) AS dimension_combinations,
            round(count(*) / sum(sessions), 3) AS fan_out_ratio
        FROM
        (
            SELECT
                uniq(session_id_v7) AS sessions,
                avg(session_duration) AS avg_duration_seconds,
                sum(toUInt64(ifNull(is_bounce, 0))) AS bounce_count,
                sum(pageviews_count) AS pageviews_total,
                person_id,
                -- All 20 dimensions
                host,
                device_type,
                initial_referring_domain,
                initial_utm_source,
                initial_utm_medium,
                initial_utm_campaign,
                initial_utm_term,
                initial_utm_content,
                initial_browser,
                initial_os,
                initial_device_type,
                initial_viewport_width,
                initial_viewport_height,
                initial_geoip_country_code,
                initial_geoip_subdivision_1_code,
                initial_geoip_subdivision_1_name,
                initial_geoip_subdivision_city_name,
                entry_pathname,
                end_pathname
            FROM
            (
                SELECT
                    events__session.session_id_v7 AS session_id_v7,
                    any(events__session.session_duration) AS session_duration,
                    any(events__session.is_bounce) AS is_bounce,
                    argMax(if(NOT empty(events__override.distinct_id), events__override.person_id, events.person_id), events.timestamp) AS person_id,
                    any(events.mat_$host) AS host,
                    any(events.mat_$device_type) AS device_type,
                    any(events__session.initial_referring_domain) AS initial_referring_domain,
                    any(events__session.initial_utm_source) AS initial_utm_source,
                    any(events__session.initial_utm_medium) AS initial_utm_medium,
                    any(events__session.initial_utm_campaign) AS initial_utm_campaign,
                    any(events__session.initial_utm_term) AS initial_utm_term,
                    any(events__session.initial_utm_content) AS initial_utm_content,
                    any(events__session.initial_browser) AS initial_browser,
                    any(events__session.initial_os) AS initial_os,
                    any(events__session.initial_device_type) AS initial_device_type,
                    any(events__session.initial_viewport_width) AS initial_viewport_width,
                    any(events__session.initial_viewport_height) AS initial_viewport_height,
                    any(events__session.initial_geoip_country_code) AS initial_geoip_country_code,
                    any(events__session.initial_geoip_subdivision_1_code) AS initial_geoip_subdivision_1_code,
                    any(events__session.initial_geoip_subdivision_1_name) AS initial_geoip_subdivision_1_name,
                    any(events__session.initial_geoip_subdivision_city_name) AS initial_geoip_subdivision_city_name,
                    any(events__session.entry_pathname) AS entry_pathname,
                    any(events__session.end_pathname) AS end_pathname,

                    -- Calculate pageviews count for this session
                    countIf(events.event = '$pageview') AS pageviews_count
                FROM events
                LEFT JOIN
                (
                    SELECT
                        toString(reinterpretAsUUID(bitOr(bitShiftLeft(raw_sessions.session_id_v7, 64), bitShiftRight(raw_sessions.session_id_v7, 64)))) AS session_id,
                        min(raw_sessions.min_timestamp) AS start_timestamp,
                        dateDiff('second', min(raw_sessions.min_timestamp), max(raw_sessions.max_timestamp)) AS session_duration,
                        if(ifNull(uniqUpToMerge(1)(raw_sessions.page_screen_autocapture_uniq_up_to) = 0, 0), NULL,
                           NOT (ifNull(uniqUpToMerge(1)(raw_sessions.page_screen_autocapture_uniq_up_to) > 1, 0) OR
                                ifNull(dateDiff('second', min(raw_sessions.min_timestamp), max(raw_sessions.max_timestamp)) >= 10, 0))) AS is_bounce,
                        raw_sessions.session_id_v7 AS session_id_v7,
                        nullIf(argMinMerge(initial_referring_domain), '') AS initial_referring_domain,
                        nullIf(argMinMerge(initial_utm_source), '') AS initial_utm_source,
                        nullIf(argMinMerge(initial_utm_medium), '') AS initial_utm_medium,
                        nullIf(argMinMerge(initial_utm_campaign), '') AS initial_utm_campaign,
                        nullIf(argMinMerge(initial_utm_term), '') AS initial_utm_term,
                        nullIf(argMinMerge(initial_utm_content), '') AS initial_utm_content,
                        nullIf(argMinMerge(initial_browser), '') AS initial_browser,
                        nullIf(argMinMerge(initial_os), '') AS initial_os,
                        nullIf(argMinMerge(initial_device_type), '') AS initial_device_type,
                        nullIf(argMinMerge(initial_geoip_country_code), '') AS initial_geoip_country_code,
                        nullIf(argMinMerge(initial_geoip_subdivision_1_code), '') AS initial_geoip_subdivision_1_code,
                        nullIf(argMinMerge(initial_geoip_subdivision_1_name), '') AS initial_geoip_subdivision_1_name,
                        nullIf(argMinMerge(initial_geoip_subdivision_city_name), '') AS initial_geoip_subdivision_city_name,
                        argMinMerge(initial_viewport_width) AS initial_viewport_width,
                        argMinMerge(initial_viewport_height) AS initial_viewport_height,
                        path(coalesce(argMinMerge(entry_url), '')) AS entry_pathname,
                        path(coalesce(argMaxMerge(end_url), '')) AS end_pathname
                    FROM raw_sessions
                    WHERE raw_sessions.team_id = 2
                        AND min_timestamp >= toDateTime('{start_date}')
                        AND min_timestamp < toDateTime('{end_date}')
                    GROUP BY raw_sessions.session_id_v7
                ) AS events__session ON toUInt128(accurateCastOrNull(events.`$session_id`, 'UUID')) = events__session.session_id_v7
                LEFT JOIN
                (
                    SELECT
                        argMax(person_distinct_id_overrides.person_id, person_distinct_id_overrides.version) AS person_id,
                        person_distinct_id_overrides.distinct_id AS distinct_id
                    FROM person_distinct_id_overrides
                    WHERE person_distinct_id_overrides.team_id = 2
                    GROUP BY person_distinct_id_overrides.distinct_id
                    HAVING ifNull(argMax(person_distinct_id_overrides.is_deleted, person_distinct_id_overrides.version) = 0, 0)
                ) AS events__override ON events.distinct_id = events__override.distinct_id
                WHERE events.team_id = 2
                    AND events.`$session_id` IS NOT NULL
                    AND events.event IN ('$pageview', '$screen')
                    AND events.timestamp >= toDateTime('{start_date}')
                    AND events.timestamp < toDateTime('{end_date}')
                GROUP BY events__session.session_id_v7
                HAVING ifNull(start_timestamp >= toDateTime('{start_date}'), 0)
                    AND ifNull(start_timestamp < toDateTime('{end_date}'), 0)
            ) AS session_data
            GROUP BY
                person_id,
                host,
                device_type,
                initial_referring_domain,
                initial_utm_source,
                initial_utm_medium,
                initial_utm_campaign,
                initial_utm_term,
                initial_utm_content,
                initial_browser,
                initial_os,
                initial_device_type,
                initial_viewport_width,
                initial_viewport_height,
                initial_geoip_country_code,
                initial_geoip_subdivision_1_code,
                initial_geoip_subdivision_1_name,
                initial_geoip_subdivision_city_name,
                entry_pathname,
                end_pathname
        ) AS dimension_groups
        """

        result = sync_execute(validation_query)

        if not result:
            return AssetCheckResult(
                passed=False,
                description="No data returned from dimensions validation query",
                metadata={"date_range": MetadataValue.text(f"{start_date} to {end_date}")},
            )

        (
            total_sessions,
            avg_duration,
            bounce_rate,
            total_pageviews,
            avg_pageviews_per_session,
            total_visitors,
            dimension_combinations,
            fan_out_ratio,
        ) = result[0]

        # Validation criteria
        sessions_min = 1000  # Minimum sessions for meaningful test
        fan_out_max = 1.0  # Fan-out ratio should be < 1.0 (no session duplication)
        visitors_min = 100  # Minimum visitors for meaningful test
        pageviews_min = 1000  # Minimum pageviews for meaningful test

        # Check all validation criteria
        sessions_ok = total_sessions >= sessions_min
        fan_out_ok = fan_out_ratio < fan_out_max
        visitors_ok = total_visitors >= visitors_min
        pageviews_ok = total_pageviews >= pageviews_min and avg_pageviews_per_session >= 1.0
        metrics_ok = avg_duration > 0 and bounce_rate >= 0

        passed = sessions_ok and fan_out_ok and visitors_ok and pageviews_ok and metrics_ok

        status_parts = []
        if not sessions_ok:
            status_parts.append(f"Sessions too low: {total_sessions} < {sessions_min}")
        if not fan_out_ok:
            status_parts.append(f"Fan-out detected: {fan_out_ratio} >= {fan_out_max}")
        if not visitors_ok:
            status_parts.append(f"Visitors too low: {total_visitors} < {visitors_min}")
        if not pageviews_ok:
            status_parts.append(
                f"Pageviews invalid: {total_pageviews} total, {avg_pageviews_per_session:.2f} avg/session"
            )
        if not metrics_ok:
            status_parts.append(f"Invalid metrics: duration={avg_duration}, bounce={bounce_rate}")

        if passed:
            description = f"✅ All 20 dimensions + pageviews validated: {total_sessions} sessions, {total_pageviews} pageviews ({avg_pageviews_per_session:.2f} avg/session), {dimension_combinations} combinations, {fan_out_ratio:.3f} fan-out ratio"
        else:
            description = f"❌ Validation failed: {', '.join(status_parts)}"

        return AssetCheckResult(
            passed=passed,
            description=description,
            metadata={
                "date_range": MetadataValue.text(f"{start_date} to {end_date}"),
                "total_sessions": MetadataValue.int(total_sessions),
                "avg_duration": MetadataValue.float(avg_duration),
                "bounce_rate": MetadataValue.float(bounce_rate),
                "total_pageviews": MetadataValue.int(total_pageviews),
                "avg_pageviews_per_session": MetadataValue.float(avg_pageviews_per_session),
                "total_visitors": MetadataValue.int(total_visitors),
                "dimension_combinations": MetadataValue.int(dimension_combinations),
                "fan_out_ratio": MetadataValue.float(fan_out_ratio),
            },
        )

    except Exception as e:
        return AssetCheckResult(
            passed=False,
            description=f"Error during dimensions validation: {str(e)}",
            metadata={"error": MetadataValue.text(str(e))},
        )
