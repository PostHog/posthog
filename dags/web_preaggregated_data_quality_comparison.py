from datetime import datetime, timedelta

import dagster
import structlog
from dagster import AssetExecutionContext, AssetMaterialization, Field, MetadataValue, WeeklyPartitionsDefinition, asset

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.query_tagging import tags_context

from dags.common import JobOwners, dagster_tags
from dags.web_preaggregated_utils import (
    TEAM_ID_FOR_WEB_ANALYTICS_ASSET_CHECKS,
    WEB_PRE_AGGREGATED_CLICKHOUSE_SETTINGS,
    format_clickhouse_settings,
)

logger = structlog.get_logger(__name__)

WEB_PRE_AGGREGATED_ACCURACY_CONFIG_SCHEMA = {
    "team_id": Field(
        int,
        default_value=TEAM_ID_FOR_WEB_ANALYTICS_ASSET_CHECKS,
        description="Team ID to analyze data quality for (use 0 for all teams)",
    ),
    "days_back": Field(
        int,
        default_value=7,
        description="Number of days back to analyze",
    ),
}


def build_accuracy_comparison_query(team_id: int, start_date: str, end_date: str, all_teams: bool = False) -> str:
    """Build the accuracy comparison query for regular vs V2 pre-aggregated data."""

    # For multi-team mode, get teams from web_pre_aggregated_teams
    if all_teams:
        team_filter = "team_id IN (SELECT team_id FROM web_pre_aggregated_teams FINAL WHERE version = (SELECT MAX(version) FROM web_pre_aggregated_teams))"
    else:
        team_filter = f"team_id = {team_id}"
    group_by_team = "team_id, " if all_teams else ""

    return f"""
WITH
    -- Method 1: Regular event count from events table - unique users (session-based like web analytics)
    regular_events AS (
        SELECT
            team_id,
            toDate(start_timestamp) as period_bucket_date,
            uniq(session_person_id) as unique_user_count
        FROM (
            SELECT
                events.team_id as team_id,
                any(events.person_id) as session_person_id,
                events__session.session_id as session_id,
                min(events__session.$start_timestamp) as start_timestamp
            FROM events
            LEFT JOIN (
                SELECT
                    raw_sessions.team_id as team_id,
                    toString(reinterpretAsUUID(bitOr(bitShiftLeft(raw_sessions.session_id_v7, 64), bitShiftRight(raw_sessions.session_id_v7, 64)))) AS session_id,
                    min(toTimeZone(raw_sessions.min_timestamp, 'UTC')) AS $start_timestamp,
                    raw_sessions.session_id_v7 AS session_id_v7
                FROM raw_sessions
                WHERE
                    {team_filter.replace("team_id", "raw_sessions.team_id")}
                    AND greaterOrEquals(fromUnixTimestamp(intDiv(toUInt64(bitShiftRight(raw_sessions.session_id_v7, 80)), 1000)), toDateTime('{start_date} 00:00:00'))
                    AND lessOrEquals(fromUnixTimestamp(intDiv(toUInt64(bitShiftRight(raw_sessions.session_id_v7, 80)), 1000)), toDateTime('{end_date} 23:59:59'))
                GROUP BY raw_sessions.team_id, raw_sessions.session_id_v7
            ) AS events__session ON events.team_id = events__session.team_id AND equals(toUInt128(accurateCastOrNull(events.$session_id, 'UUID')), events__session.session_id_v7)
            WHERE
                {team_filter.replace("team_id", "events.team_id")}
                AND timestamp >= toDateTime('{start_date} 00:00:00')
                AND timestamp <= toDateTime('{end_date} 23:59:59')
                AND event IN ('$pageview', '$screen')
                AND $session_id IS NOT NULL
                AND events__session.session_id IS NOT NULL
            GROUP BY events.team_id, session_id
            HAVING start_timestamp >= toDateTime('{start_date} 00:00:00')
               AND start_timestamp <= toDateTime('{end_date} 23:59:59')
        )
        GROUP BY {group_by_team}period_bucket_date
    ),

    -- Method 2: V2 Pre-aggregated tables (hourly)
    pre_aggregated AS (
        SELECT
            team_id,
            toDate(period_bucket) as period_bucket_date,
            uniqMerge(persons_uniq_state) as unique_user_count
        FROM web_pre_aggregated_bounces
        WHERE
            {team_filter}
            AND period_bucket >= toDateTime('{start_date} 00:00:00')
            AND period_bucket <= toDateTime('{end_date} 23:59:59')
        GROUP BY {group_by_team}period_bucket_date
    )

-- Final comparison with percentage differences
SELECT
    COALESCE(r.team_id, p.team_id) as team_id,
    COALESCE(r.period_bucket_date, p.period_bucket_date) as period_bucket_date,

    -- Raw counts
    COALESCE(r.unique_user_count, 0) as regular_count,
    COALESCE(p.unique_user_count, 0) as pre_aggregated_count,

    -- Percentage difference (using regular events as baseline)
    CASE
        WHEN r.unique_user_count = 0 AND p.unique_user_count = 0 THEN 0
        WHEN r.unique_user_count = 0 THEN 100
        ELSE round(abs(r.unique_user_count - p.unique_user_count) / r.unique_user_count * 100, 2)
    END as pct_difference,

    -- Within tolerance flag (>1% difference)
    CASE
        WHEN abs(COALESCE(r.unique_user_count, 0) - COALESCE(p.unique_user_count, 0)) / greatest(COALESCE(r.unique_user_count, 1), 1) * 100 <= 1
        THEN 'YES'
        ELSE 'NO'
    END as within_tolerance,

    -- Quality status
    CASE
        WHEN abs(COALESCE(r.unique_user_count, 0) - COALESCE(p.unique_user_count, 0)) / greatest(COALESCE(r.unique_user_count, 1), 1) * 100 <= 1 THEN 'GOOD'
        WHEN abs(COALESCE(r.unique_user_count, 0) - COALESCE(p.unique_user_count, 0)) / greatest(COALESCE(r.unique_user_count, 1), 1) * 100 <= 5 THEN 'FAIR'
        ELSE 'POOR'
    END as quality_status

FROM regular_events r
FULL OUTER JOIN pre_aggregated p ON {"r.team_id = p.team_id AND " if all_teams else ""}r.period_bucket_date = p.period_bucket_date
ORDER BY team_id, period_bucket_date DESC
    """


@asset(
    name="web_pre_aggregated_accuracy",
    description="Accuracy comparison of unique user counts between regular events and V2 pre-aggregated tables",
    config_schema=WEB_PRE_AGGREGATED_ACCURACY_CONFIG_SCHEMA,
    partitions_def=WeeklyPartitionsDefinition(start_date="2024-01-01"),
    tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value},
)
def web_pre_aggregated_accuracy(context: AssetExecutionContext) -> AssetMaterialization:
    """
    Compares data accuracy between regular events and V2 pre-aggregated tables.
    Outputs table-like format suitable for future ClickHouse table integration.

    Table columns: team_id, period_bucket_date, regular_count, pre_aggregated_count,
                   pct_difference, within_tolerance, quality_status
    """

    # Get configuration
    team_id = context.op_config["team_id"]
    days_back = context.op_config["days_back"]

    if days_back < 1:
        raise dagster.Failure(f"days_back must be at least 1, got {days_back}")

    all_teams = team_id == 0

    # Calculate date range based on partition key
    if context.partition_key:
        # Use partition date (end of week) if partitioned
        partition_date = datetime.strptime(context.partition_key, "%Y-%m-%d").date()
        end_date = partition_date
        start_date = end_date - timedelta(days=days_back)
    else:
        # Fallback to current date if not partitioned (for manual runs)
        end_date = (datetime.now() - timedelta(days=1)).date()
        start_date = end_date - timedelta(days=days_back)

    start_date_str = start_date.strftime("%Y-%m-%d")
    end_date_str = end_date.strftime("%Y-%m-%d")

    mode = "all teams" if all_teams else f"team {team_id}"
    context.log.info(f"Running accuracy comparison for {mode} from {start_date_str} to {end_date_str}")

    # Build and execute query
    query = build_accuracy_comparison_query(team_id, start_date_str, end_date_str, all_teams)
    clickhouse_settings = format_clickhouse_settings(WEB_PRE_AGGREGATED_CLICKHOUSE_SETTINGS)

    try:
        with tags_context(kind="dagster", dagster=dagster_tags(context)):
            context.log.info("Executing accuracy comparison query")
            result = sync_execute(query, settings=clickhouse_settings)

        context.log.info(f"Query returned {len(result)} rows")

        # Process results into table-like format
        table_rows = []
        total_rows = 0
        within_tolerance_count = 0
        max_pct_difference = 0.0

        for row in result:
            (
                team_id_val,
                period_bucket_date,
                regular_count,
                pre_aggregated_count,
                pct_difference,
                within_tolerance,
                quality_status,
            ) = row

            table_rows.append(
                {
                    "team_id": int(team_id_val),
                    "period_bucket_date": str(period_bucket_date),
                    "regular_count": int(regular_count),
                    "pre_aggregated_count": int(pre_aggregated_count),
                    "pct_difference": float(pct_difference),
                    "within_tolerance": within_tolerance,
                    "quality_status": quality_status,
                }
            )

            total_rows += 1
            if within_tolerance == "YES":
                within_tolerance_count += 1
            max_pct_difference = max(max_pct_difference, float(pct_difference))

        # Calculate summary statistics
        accuracy_rate = (within_tolerance_count / max(total_rows, 1)) * 100

        # Determine overall status
        if accuracy_rate >= 95:
            overall_status = "EXCELLENT"
        elif accuracy_rate >= 90:
            overall_status = "GOOD"
        elif accuracy_rate >= 80:
            overall_status = "FAIR"
        else:
            overall_status = "POOR"

        context.log.info(
            f"Accuracy analysis complete: {overall_status} - "
            f"{accuracy_rate:.1f}% within tolerance ({within_tolerance_count}/{total_rows} rows)"
        )

        metadata = {
            # Summary metrics
            "mode": MetadataValue.text("all_teams" if all_teams else f"team_{team_id}"),
            "date_range": MetadataValue.text(f"{start_date_str} to {end_date_str}"),
            "total_rows": MetadataValue.int(total_rows),
            "within_tolerance_count": MetadataValue.int(within_tolerance_count),
            "accuracy_rate": MetadataValue.float(accuracy_rate),
            "overall_status": MetadataValue.text(overall_status),
            "max_pct_difference": MetadataValue.float(max_pct_difference),
            # Table-like results (ready for future ClickHouse table)
            "accuracy_table": MetadataValue.json(table_rows),
            # Configuration
            "days_back": MetadataValue.int(days_back),
        }

        if context.partition_key:
            metadata["partition_key"] = MetadataValue.text(context.partition_key)

        return AssetMaterialization(
            asset_key="web_pre_aggregated_accuracy",
            metadata=metadata,
        )

    except Exception as e:
        context.log.exception(f"Error executing accuracy comparison: {str(e)}")
        raise dagster.Failure(f"Accuracy comparison failed: {str(e)}")
