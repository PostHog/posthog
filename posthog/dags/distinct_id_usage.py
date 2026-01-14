import io
import csv
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import dagster
import pydantic
import dagster_slack
from clickhouse_driver import Client

from posthog import settings
from posthog.clickhouse.cluster import ClickhouseCluster
from posthog.dags.common import JobOwners, settings_with_log_comment
from posthog.models.distinct_id_usage.sql import TABLE_BASE_NAME

JOB_NAME = "distinct_id_usage_monitoring"


class DistinctIdUsageMonitoringConfig(dagster.Config):
    """Configuration for distinct_id usage monitoring thresholds."""

    high_usage_percentage_threshold: int = pydantic.Field(
        default=30,
        description="Percentage of events from a single distinct_id that triggers an alert (0-100)",
    )
    high_cardinality_threshold: int = pydantic.Field(
        default=1_000_000,
        description="Number of unique distinct_ids per team that triggers a high cardinality alert",
    )
    burst_threshold: int = pydantic.Field(
        default=10_000,
        description="Events per minute from a single (team, distinct_id) that triggers a burst alert",
    )
    default_lookback_hours: int = pydantic.Field(
        default=6,
        description="Default lookback hours if no previous successful run is found",
    )


@dataclass
class HighUsageDistinctId:
    team_id: int
    distinct_id: str
    event_count: int
    total_team_events: int
    percentage: float


@dataclass
class HighCardinalityTeam:
    team_id: int
    distinct_id_count: int


@dataclass
class BurstEvent:
    team_id: int
    distinct_id: str
    minute: str
    event_count: int


@dataclass
class MonitoringResults:
    high_usage: list[HighUsageDistinctId]
    high_cardinality: list[HighCardinalityTeam]
    bursts: list[BurstEvent]
    lookback_start: datetime


def get_last_successful_run_time(context: dagster.OpExecutionContext) -> datetime | None:
    """Get the end time of the last successful run of this job."""
    run_records = context.instance.get_run_records(
        dagster.RunsFilter(
            job_name=JOB_NAME,
            statuses=[dagster.DagsterRunStatus.SUCCESS],
        ),
        limit=1,
    )

    if run_records and run_records[0].end_time:
        return datetime.fromtimestamp(run_records[0].end_time, tz=UTC)

    return None


@dagster.op
def query_distinct_id_usage(
    context: dagster.OpExecutionContext,
    config: DistinctIdUsageMonitoringConfig,
    cluster: dagster.ResourceParam[ClickhouseCluster],
) -> MonitoringResults:
    """Query the distinct_id_usage table to find problematic patterns."""

    last_run_time = get_last_successful_run_time(context)

    if last_run_time:
        lookback_start = last_run_time
        context.log.info(f"Using last successful run time as lookback start: {lookback_start}")
    else:
        lookback_start = datetime.now(tz=UTC) - timedelta(hours=config.default_lookback_hours)
        context.log.info(f"No previous successful run found, using default lookback: {lookback_start}")

    def run_queries(client: Client) -> MonitoringResults:
        query_settings = settings_with_log_comment(context)

        # Query 1: Find distinct_ids with high percentage of team's events
        high_usage_query = f"""
        WITH team_totals AS (
            SELECT
                team_id,
                sum(event_count) as total_events
            FROM {settings.CLICKHOUSE_DATABASE}.{TABLE_BASE_NAME}
            WHERE minute >= %(lookback_start)s
            GROUP BY team_id
            HAVING total_events > 0
        ),
        distinct_id_totals AS (
            SELECT
                team_id,
                distinct_id,
                sum(event_count) as event_count
            FROM {settings.CLICKHOUSE_DATABASE}.{TABLE_BASE_NAME}
            WHERE minute >= %(lookback_start)s
            GROUP BY team_id, distinct_id
        )
        SELECT
            d.team_id,
            d.distinct_id,
            d.event_count,
            t.total_events,
            round(d.event_count * 100.0 / t.total_events, 2) as percentage
        FROM distinct_id_totals d
        JOIN team_totals t ON d.team_id = t.team_id
        WHERE d.event_count * 100.0 / t.total_events >= %(threshold)s
        ORDER BY percentage DESC
        LIMIT 100
        """

        high_usage_results = client.execute(
            high_usage_query,
            {
                "lookback_start": lookback_start,
                "threshold": config.high_usage_percentage_threshold,
            },
            settings=query_settings,
        )

        high_usage = [
            HighUsageDistinctId(
                team_id=row[0],
                distinct_id=row[1],
                event_count=row[2],
                total_team_events=row[3],
                percentage=row[4],
            )
            for row in high_usage_results
        ]

        # Query 2: Find teams with high distinct_id cardinality
        high_cardinality_query = f"""
        SELECT
            team_id,
            uniq(distinct_id) as distinct_id_count
        FROM {settings.CLICKHOUSE_DATABASE}.{TABLE_BASE_NAME}
        WHERE minute >= %(lookback_start)s
        GROUP BY team_id
        HAVING distinct_id_count >= %(threshold)s
        ORDER BY distinct_id_count DESC
        LIMIT 100
        """

        high_cardinality_results = client.execute(
            high_cardinality_query,
            {
                "lookback_start": lookback_start,
                "threshold": config.high_cardinality_threshold,
            },
            settings=query_settings,
        )

        high_cardinality = [
            HighCardinalityTeam(team_id=row[0], distinct_id_count=row[1]) for row in high_cardinality_results
        ]

        # Query 3: Find burst events (high events per minute)
        burst_query = f"""
        SELECT
            team_id,
            distinct_id,
            minute,
            sum(event_count) as event_count
        FROM {settings.CLICKHOUSE_DATABASE}.{TABLE_BASE_NAME}
        WHERE minute >= %(lookback_start)s
        GROUP BY team_id, distinct_id, minute
        HAVING event_count >= %(threshold)s
        ORDER BY event_count DESC
        LIMIT 100
        """

        burst_results = client.execute(
            burst_query,
            {
                "lookback_start": lookback_start,
                "threshold": config.burst_threshold,
            },
            settings=query_settings,
        )

        bursts = [
            BurstEvent(
                team_id=row[0],
                distinct_id=row[1],
                minute=str(row[2]),
                event_count=row[3],
            )
            for row in burst_results
        ]

        return MonitoringResults(
            high_usage=high_usage,
            high_cardinality=high_cardinality,
            bursts=bursts,
            lookback_start=lookback_start,
        )

    results = cluster.any_host(run_queries).result()

    context.log.info(f"Found {len(results.high_usage)} high usage distinct_ids")
    context.log.info(f"Found {len(results.high_cardinality)} high cardinality teams")
    context.log.info(f"Found {len(results.bursts)} burst events")

    return results


def generate_csv_report(results: MonitoringResults) -> str:
    """Generate a CSV report with all detected issues."""
    output = io.StringIO()
    writer = csv.writer(output)

    # High usage section
    writer.writerow(["=== HIGH USAGE DISTINCT IDS ==="])
    writer.writerow(["team_id", "distinct_id", "event_count", "total_team_events", "percentage"])
    for item in results.high_usage:
        writer.writerow([item.team_id, item.distinct_id, item.event_count, item.total_team_events, item.percentage])

    writer.writerow([])

    # High cardinality section
    writer.writerow(["=== HIGH CARDINALITY TEAMS ==="])
    writer.writerow(["team_id", "distinct_id_count"])
    for item in results.high_cardinality:
        writer.writerow([item.team_id, item.distinct_id_count])

    writer.writerow([])

    # Bursts section
    writer.writerow(["=== BURST EVENTS ==="])
    writer.writerow(["team_id", "distinct_id", "minute", "event_count"])
    for item in results.bursts:
        writer.writerow([item.team_id, item.distinct_id, item.minute, item.event_count])

    return output.getvalue()


def truncate_distinct_id(distinct_id: str, max_length: int = 30) -> str:
    """Truncate distinct_id for display, adding ellipsis if needed."""
    if len(distinct_id) <= max_length:
        return distinct_id
    return distinct_id[: max_length - 3] + "..."


@dagster.op
def send_alerts(
    context: dagster.OpExecutionContext,
    results: MonitoringResults,
    slack: dagster_slack.SlackResource,
) -> None:
    """Send Slack alerts for any detected issues."""

    if not results.high_usage and not results.high_cardinality and not results.bursts:
        context.log.info("No issues detected, skipping alerts")
        return

    if not settings.CLOUD_DEPLOYMENT:
        context.log.info("Skipping Slack notification in non-prod environment")
        return

    total_issues = len(results.high_usage) + len(results.high_cardinality) + len(results.bursts)
    lookback_info = f"Since: {results.lookback_start.strftime('%Y-%m-%d %H:%M:%S')} UTC"

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "Distinct ID Usage Alert", "emoji": True},
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"Environment: {settings.CLOUD_DEPLOYMENT} | {lookback_info} | Total issues: {total_issues}",
                }
            ],
        },
    ]

    # Show top 3 for each category
    if results.high_usage:
        high_usage_text = f"*High Usage Distinct IDs* ({len(results.high_usage)} found):\n"
        for item in results.high_usage[:3]:
            high_usage_text += f"• Team `{item.team_id}`: `{truncate_distinct_id(item.distinct_id)}` - {item.percentage}% ({item.event_count:,} events)\n"
        if len(results.high_usage) > 3:
            high_usage_text += f"_...and {len(results.high_usage) - 3} more in attached report_\n"
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": high_usage_text}})

    if results.high_cardinality:
        cardinality_text = f"*High Cardinality Teams* ({len(results.high_cardinality)} found):\n"
        for item in results.high_cardinality[:3]:
            cardinality_text += f"• Team `{item.team_id}`: {item.distinct_id_count:,} unique distinct_ids\n"
        if len(results.high_cardinality) > 3:
            cardinality_text += f"_...and {len(results.high_cardinality) - 3} more in attached report_\n"
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": cardinality_text}})

    if results.bursts:
        burst_text = f"*Burst Events* ({len(results.bursts)} found):\n"
        for item in results.bursts[:3]:
            burst_text += f"• Team `{item.team_id}`: `{truncate_distinct_id(item.distinct_id)}` at {item.minute} - {item.event_count:,} events/min\n"
        if len(results.bursts) > 3:
            burst_text += f"_...and {len(results.bursts) - 3} more in attached report_\n"
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": burst_text}})

    try:
        slack_client = slack.get_client()
        channel = settings.DAGSTER_DEFAULT_SLACK_ALERTS_CHANNEL

        # Post the summary message
        slack_client.chat_postMessage(channel=channel, blocks=blocks)

        # Upload detailed report as a file
        csv_report = generate_csv_report(results)
        timestamp = datetime.now(tz=UTC).strftime("%Y%m%d_%H%M%S")
        slack_client.files_upload_v2(
            channel=channel,
            content=csv_report,
            filename=f"distinct_id_usage_report_{timestamp}.csv",
            title="Distinct ID Usage Report",
            initial_comment="Full report attached:",
        )

        context.log.info("Sent Slack alert with attached report for distinct_id usage issues")
    except Exception as e:
        context.log.exception(f"Failed to send Slack notification: {e}")


@dagster.job(tags={"owner": JobOwners.TEAM_INGESTION.value})
def distinct_id_usage_monitoring():
    """Monitor distinct_id usage patterns and alert on anomalies."""
    results = query_distinct_id_usage()
    send_alerts(results)


distinct_id_usage_monitoring_schedule = dagster.ScheduleDefinition(
    job=distinct_id_usage_monitoring,
    cron_schedule="0 */6 * * *",  # Every 6 hours
    execution_timezone="UTC",
    name="distinct_id_usage_monitoring_schedule",
)
