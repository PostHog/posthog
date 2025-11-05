from datetime import datetime, timedelta

import dagster
import pydantic
from dagster import AssetExecutionContext, MetadataValue, WeeklyPartitionsDefinition, asset

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.query_tagging import tags_context

from dags.common import JobOwners, dagster_tags
from dags.web_preaggregated_utils import TEAM_ID_FOR_WEB_ANALYTICS_ASSET_CHECKS, WEB_PRE_AGGREGATED_CLICKHOUSE_SETTINGS


class AccuracyConfig(dagster.Config):
    team_id: int = pydantic.Field(
        default=int(TEAM_ID_FOR_WEB_ANALYTICS_ASSET_CHECKS),
        description="Team ID to analyze data quality for",
    )


def build_accuracy_comparison_query(team_id: int, start_date: str, end_date: str) -> str:
    return f"""
WITH
    -- Method 1: Regular event count from events table - unique users (session-based like web analytics)
    regular_events AS (
        SELECT
            toDate(start_timestamp) as period_bucket_date,
            uniq(session_person_id) as unique_user_count
        FROM (
            SELECT
                any(events.person_id) as session_person_id,
                events__session.session_id as session_id,
                min(events__session.$start_timestamp) as start_timestamp
            FROM events
            LEFT JOIN (
                SELECT
                    toString(reinterpretAsUUID(bitOr(bitShiftLeft(raw_sessions.session_id_v7, 64), bitShiftRight(raw_sessions.session_id_v7, 64)))) AS session_id,
                    min(toTimeZone(raw_sessions.min_timestamp, 'UTC')) AS $start_timestamp,
                    raw_sessions.session_id_v7 AS session_id_v7
                FROM raw_sessions
                WHERE
                    raw_sessions.team_id = {team_id}
                    AND greaterOrEquals(fromUnixTimestamp(intDiv(toUInt64(bitShiftRight(raw_sessions.session_id_v7, 80)), 1000)), toDateTime('{start_date} 00:00:00'))
                    AND lessOrEquals(fromUnixTimestamp(intDiv(toUInt64(bitShiftRight(raw_sessions.session_id_v7, 80)), 1000)), toDateTime('{end_date} 23:59:59'))
                GROUP BY raw_sessions.session_id_v7
            ) AS events__session ON equals(toUInt128(accurateCastOrNull(events.$session_id, 'UUID')), events__session.session_id_v7)
            WHERE
                team_id = {team_id}
                AND timestamp >= toDateTime('{start_date} 00:00:00')
                AND timestamp <= toDateTime('{end_date} 23:59:59')
                AND event IN ('$pageview', '$screen')
                AND $session_id IS NOT NULL
                AND events__session.session_id IS NOT NULL
            GROUP BY session_id
            HAVING start_timestamp >= toDateTime('{start_date} 00:00:00')
               AND start_timestamp <= toDateTime('{end_date} 23:59:59')
        )
        GROUP BY period_bucket_date
    ),

    -- Method 2: V2 Pre-aggregated tables (hourly)
    pre_aggregated AS (
        SELECT
            toDate(period_bucket) as period_bucket_date,
            uniqMerge(persons_uniq_state) as unique_user_count
        FROM web_pre_aggregated_bounces
        WHERE
            team_id = {team_id}
            AND period_bucket >= toDateTime('{start_date} 00:00:00')
            AND period_bucket <= toDateTime('{end_date} 23:59:59')
        GROUP BY period_bucket_date
    )

-- Final comparison with percentage differences
SELECT
    {team_id} as team_id,
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
FULL OUTER JOIN pre_aggregated p ON r.period_bucket_date = p.period_bucket_date
ORDER BY period_bucket_date DESC
    """


@asset(
    name="web_pre_aggregated_accuracy",
    description="Accuracy comparison of unique user counts between regular events and V2 pre-aggregated tables",
    partitions_def=WeeklyPartitionsDefinition(start_date="2024-01-01", end_offset=1),
    tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value},
)
def web_pre_aggregated_accuracy(context: AssetExecutionContext, config: AccuracyConfig) -> list[dict]:
    team_id = config.team_id

    partition_date = datetime.strptime(context.partition_key, "%Y-%m-%d").date()
    end_date = partition_date
    start_date = end_date - timedelta(days=6)

    start_date_str = start_date.strftime("%Y-%m-%d")
    end_date_str = end_date.strftime("%Y-%m-%d")

    context.log.info(f"Running accuracy comparison for team {team_id} from {start_date_str} to {end_date_str}")

    query = build_accuracy_comparison_query(team_id, start_date_str, end_date_str)

    try:
        context.log.info(query)

        with tags_context(kind="dagster", dagster=dagster_tags(context)):
            context.log.info("Executing accuracy comparison query")
            result = sync_execute(query, settings=WEB_PRE_AGGREGATED_CLICKHOUSE_SETTINGS)

        context.log.info(f"Query returned {len(result)} rows")

        table_rows = [
            {
                "team_id": int(row[0]),
                "period_bucket_date": str(row[1]),
                "regular_count": int(row[2]),
                "pre_aggregated_count": int(row[3]),
                "pct_difference": float(row[4]),
                "within_tolerance": row[5],
                "quality_status": row[6],
            }
            for row in result
        ]

        total_rows = len(table_rows)
        within_tolerance_count = sum(1 for row in table_rows if row["within_tolerance"] == "YES")
        max_pct_difference = max((row["pct_difference"] for row in table_rows), default=0.0)
        accuracy_rate = (within_tolerance_count / max(total_rows, 1)) * 100

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

        context.log.info(table_rows)

        rows_md = "\n".join(
            f"| {row['period_bucket_date']} "
            f"| {row['regular_count']:,} "
            f"| {row['pre_aggregated_count']:,} "
            f"| {row['pct_difference']:.2f}% "
            f"| {row['within_tolerance']} "
            f"| {row['quality_status']} |"
            for row in table_rows
        )

        comparison_md = f"""
        | Date | Regular Count | Pre-Aggregated Count | Diff % | Within Tolerance | Status |
        |------|---------------|----------------------|--------|------------------|--------|
        {rows_md}""".strip()

        metadata = {
            "team_id": MetadataValue.int(team_id),
            "date_range": MetadataValue.text(f"{start_date_str} to {end_date_str}"),
            "total_rows": MetadataValue.int(total_rows),
            "within_tolerance_count": MetadataValue.int(within_tolerance_count),
            "accuracy_rate": MetadataValue.float(accuracy_rate),
            "overall_status": MetadataValue.text(overall_status),
            "max_pct_difference": MetadataValue.float(max_pct_difference),
            "comparison_table_json": MetadataValue.json(table_rows),
            "comparison_table": MetadataValue.text(comparison_md),
        }

        context.add_output_metadata(metadata)

        return table_rows

    except Exception as e:
        context.log.exception(f"Error executing accuracy comparison: {str(e)}")
        raise dagster.Failure(f"Accuracy comparison failed: {str(e)}")
