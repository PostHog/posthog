from typing import Any
import dagster
from dags.common import JobOwners
from dags.web_preaggregated_utils import (
    TEAM_ID_FOR_WEB_ANALYTICS_ASSET_CHECKS,
    web_analytics_retry_policy_def,
)
from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.escape import substitute_params
import structlog
from datetime import datetime, timedelta, UTC

logger = structlog.get_logger(__name__)


def get_regular_query_results(team_id: int, start_date: str, end_date: str) -> dict[str, float]:
    """Get results from regular (non-aggregated) queries"""
    sql = """
    SELECT
        uniq(person_id) as visitors,
        uniq(session_id) as sessions,
        sum(pageview_count) as views,
        sum(session_duration) as total_session_duration,
        sum(is_bounce) as bounces,
        sum(1) as total_sessions
    FROM (
        SELECT
            argMax(if(NOT empty(events__override.distinct_id), events__override.person_id, events.person_id), e.timestamp) AS person_id,
            events__session.session_id AS session_id,
            countIf(e.event IN ('$pageview', '$screen')) AS pageview_count,
            any(events__session.session_duration) AS session_duration,
            any(events__session.is_bounce) AS is_bounce
        FROM events AS e
        LEFT JOIN (
            SELECT
                toString(reinterpretAsUUID(bitOr(bitShiftLeft(raw_sessions.session_id_v7, 64), bitShiftRight(raw_sessions.session_id_v7, 64)))) AS session_id,
                dateDiff('second', min(toTimeZone(raw_sessions.min_timestamp, 'UTC')), max(toTimeZone(raw_sessions.max_timestamp, 'UTC'))) AS session_duration,
                if(ifNull(equals(uniqUpToMerge(1)(raw_sessions.page_screen_autocapture_uniq_up_to), 0), 0), NULL,
                    NOT(or(
                        ifNull(greater(uniqUpToMerge(1)(raw_sessions.page_screen_autocapture_uniq_up_to), 1), 0),
                        greaterOrEquals(dateDiff('second',
                        min(toTimeZone(raw_sessions.min_timestamp, 'UTC')),
                        max(toTimeZone(raw_sessions.max_timestamp, 'UTC'))), 10)
                    ))
                ) AS is_bounce,
                raw_sessions.session_id_v7 AS session_id_v7
            FROM raw_sessions
            WHERE raw_sessions.team_id = %(team_id)s
                AND toTimeZone(raw_sessions.min_timestamp, 'UTC') >= toDateTime(%(start_date)s, 'UTC')
                AND toTimeZone(raw_sessions.min_timestamp, 'UTC') < toDateTime(%(end_date)s, 'UTC')
            GROUP BY raw_sessions.session_id_v7
        ) AS events__session ON toUInt128(accurateCastOrNull(e.`$session_id`, 'UUID')) = events__session.session_id_v7
        LEFT JOIN (
            SELECT
                argMax(person_distinct_id_overrides.person_id, person_distinct_id_overrides.version) AS person_id,
                person_distinct_id_overrides.distinct_id AS distinct_id
            FROM person_distinct_id_overrides
            WHERE person_distinct_id_overrides.team_id = %(team_id)s
            GROUP BY person_distinct_id_overrides.distinct_id
            HAVING ifNull(argMax(person_distinct_id_overrides.is_deleted, person_distinct_id_overrides.version) = 0, 0)
        ) AS events__override ON e.distinct_id = events__override.distinct_id
        WHERE e.team_id = %(team_id)s
            AND ((e.event = '$pageview') OR (e.event = '$screen'))
            AND (e.`$session_id` IS NOT NULL)
            AND toTimeZone(e.timestamp, 'UTC') >= toDateTime(%(start_date)s, 'UTC')
            AND toTimeZone(e.timestamp, 'UTC') < toDateTime(%(end_date)s, 'UTC')
        GROUP BY session_id, e.team_id
    )
    """

    params = {
        "team_id": team_id,
        "start_date": start_date,
        "end_date": end_date,
    }

    query_sql = substitute_params(sql, params)
    result = sync_execute(query_sql)[0]

    bounce_rate = (result[4] / result[5] * 100) if result[5] > 0 else 0
    avg_session_duration = (result[3] / result[5]) if result[5] > 0 else 0

    return {
        "visitors": result[0],
        "sessions": result[1],
        "views": result[2],
        "bounce_rate": bounce_rate,
        "session_duration": avg_session_duration,
    }


def get_aggregated_results(team_id: int, start_date: str, end_date: str, table_name: str) -> dict[str, float]:
    """Get results from aggregated table (daily or hourly)"""
    sql = """
    SELECT
        uniqMerge(persons_uniq_state) as visitors,
        uniqMerge(sessions_uniq_state) as sessions,
        sumMerge(pageviews_count_state) as views,
        sumMerge(total_session_duration_state) as total_session_duration,
        sumMerge(bounces_count_state) as bounces,
        sumMerge(total_session_count_state) as total_sessions
    FROM {table_name}
    WHERE team_id = %(team_id)s
        AND period_bucket >= toDateTime(%(start_date)s, 'UTC')
        AND period_bucket < toDateTime(%(end_date)s, 'UTC')
    """

    params = {
        "team_id": team_id,
        "start_date": start_date,
        "end_date": end_date,
    }

    query_sql = substitute_params(sql.format(table_name=table_name), params)
    result = sync_execute(query_sql)[0]

    bounce_rate = (result[4] / result[5] * 100) if result[5] > 0 else 0
    avg_session_duration = (result[3] / result[5]) if result[5] > 0 else 0

    return {
        "visitors": result[0],
        "sessions": result[1],
        "views": result[2],
        "bounce_rate": bounce_rate,
        "session_duration": avg_session_duration,
    }


def get_daily_aggregated_results(team_id: int, start_date: str, end_date: str) -> dict[str, float]:
    """Get results from daily aggregated table"""
    return get_aggregated_results(team_id, start_date, end_date, "web_bounces_daily")


def get_hourly_aggregated_results(team_id: int, start_date: str, end_date: str) -> dict[str, float]:
    """Get results from hourly aggregated table"""
    return get_aggregated_results(team_id, start_date, end_date, "web_bounces_hourly_historical")


def calculate_differences(
    regular: dict[str, float], aggregated: dict[str, float], tolerance_pct: float
) -> dict[str, Any]:
    """Calculate percentage differences and check tolerance"""
    metrics = {}

    for metric in regular.keys():
        regular_val = regular[metric]
        aggregated_val = aggregated[metric]

        if regular_val == 0:
            pct_diff = 0 if aggregated_val == 0 else float("inf")
        else:
            pct_diff = abs(aggregated_val - regular_val) / regular_val * 100

        within_tolerance = pct_diff <= tolerance_pct

        metrics[metric] = {
            "regular": regular_val,
            "aggregated": aggregated_val,
            "pct_difference": pct_diff,
            "within_tolerance": within_tolerance,
        }

    all_within_tolerance = all(m["within_tolerance"] for m in metrics.values())

    return {
        "metrics": metrics,
        "all_within_tolerance": all_within_tolerance,
    }


def validate_inputs(team_id: int, start_date: str, end_date: str) -> None:
    """Validate inputs to prevent SQL injection and ensure data quality"""
    if not isinstance(team_id, int) or team_id <= 0:
        raise ValueError(f"Invalid team_id: {team_id}")

    try:
        datetime.strptime(start_date, "%Y-%m-%d")
        datetime.strptime(end_date, "%Y-%m-%d")
    except ValueError as e:
        raise ValueError(f"Invalid date format: {e}")

    if start_date >= end_date:
        raise ValueError("start_date must be before end_date")


@dagster.asset(
    name="web_analytics_accuracy_comparison",
    group_name="web_analytics",
    deps=["web_analytics_bounces_daily", "web_analytics_bounces_hourly_historical"],
    tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value},
    retry_policy=web_analytics_retry_policy_def,
)
def web_analytics_accuracy_comparison(context: dagster.AssetExecutionContext) -> dagster.Output[dict[str, Any]]:
    """
    Compare accuracy between daily and hourly historical web aggregations.

    This asset tests the hypothesis that hourly aggregation provides better accuracy
    than daily aggregation by comparing both against regular (non-aggregated) queries.
    """

    # Use last 7 days for comparison (UTC timezone)
    end_date = datetime.now(UTC).strftime("%Y-%m-%d")
    start_date = (datetime.now(UTC) - timedelta(days=7)).strftime("%Y-%m-%d")
    team_id = int(TEAM_ID_FOR_WEB_ANALYTICS_ASSET_CHECKS)
    tolerance_pct = 1.0

    context.log.info(f"Comparing accuracy for team {team_id} from {start_date} to {end_date}")

    try:
        # Validate inputs
        validate_inputs(team_id, start_date, end_date)

        # Get regular query results (baseline)
        regular_results = get_regular_query_results(team_id, start_date, end_date)

        # Get daily aggregated results
        daily_results = get_daily_aggregated_results(team_id, start_date, end_date)

        # Get hourly aggregated results
        hourly_results = get_hourly_aggregated_results(team_id, start_date, end_date)

        # Calculate differences
        daily_comparison = calculate_differences(regular_results, daily_results, tolerance_pct)
        hourly_comparison = calculate_differences(regular_results, hourly_results, tolerance_pct)

        comparison_results = {
            "team_id": team_id,
            "date_from": start_date,
            "date_to": end_date,
            "tolerance_pct": tolerance_pct,
            "regular_query": regular_results,
            "daily_aggregation": {
                "results": daily_results,
                "comparison": daily_comparison,
            },
            "hourly_aggregation": {
                "results": hourly_results,
                "comparison": hourly_comparison,
            },
        }

        # Log summary
        context.log.info("Accuracy comparison results:")
        for metric in daily_comparison["metrics"]:
            daily_diff = daily_comparison["metrics"][metric]["pct_difference"]
            hourly_diff = hourly_comparison["metrics"][metric]["pct_difference"]
            better = "Hourly" if hourly_diff < daily_diff else "Daily" if daily_diff < hourly_diff else "Equal"
            context.log.info(f"{metric}: Daily {daily_diff:.2f}%, Hourly {hourly_diff:.2f}% - {better} is better")

        daily_status = "✓" if daily_comparison["all_within_tolerance"] else "✗"
        hourly_status = "✓" if hourly_comparison["all_within_tolerance"] else "✗"
        context.log.info(f"All within {tolerance_pct}%: Daily {daily_status}, Hourly {hourly_status}")

        return dagster.Output(
            value=comparison_results,
            metadata={
                "team_id": team_id,
                "date_range": f"{start_date} to {end_date}",
                "daily_within_tolerance": daily_comparison["all_within_tolerance"],
                "hourly_within_tolerance": hourly_comparison["all_within_tolerance"],
                "tolerance_pct": tolerance_pct,
                "metrics_count": len(daily_comparison["metrics"]),
            },
        )

    except Exception as e:
        context.log.info(f"Failed to compare accuracy: {str(e)}")
        raise dagster.Failure(f"Failed to compare accuracy: {str(e)}") from e


# Job for accuracy comparison
web_analytics_accuracy_comparison_job = dagster.define_asset_job(
    name="web_analytics_accuracy_comparison_job",
    selection=["web_analytics_accuracy_comparison"],
    tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value},
)
