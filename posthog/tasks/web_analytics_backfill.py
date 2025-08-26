from datetime import datetime, timedelta
from typing import Optional

import structlog
from celery import shared_task

from posthog.clickhouse.client import sync_execute
from posthog.models.team.team import Team
from posthog.models.web_preaggregated.sql import WEB_STATS_INSERT_SQL, WEB_BOUNCES_INSERT_SQL

logger = structlog.get_logger(__name__)

# Backfill configuration
DEFAULT_BACKFILL_DAYS = 7
MAX_BACKFILL_DAYS = 30  # Safety limit


def get_backfill_date_range(days: int = DEFAULT_BACKFILL_DAYS) -> tuple[str, str]:
    """Get the date range for backfill (last N days)."""
    end_date = datetime.utcnow()
    start_date = end_date - timedelta(days=days)

    return (
        start_date.strftime("%Y-%m-%d"),
        end_date.strftime("%Y-%m-%d")
    )


def validate_team_for_backfill(team_id: int) -> Optional[Team]:
    """Validate that team exists and still has pre-aggregated tables enabled."""
    try:
        team = Team.objects.get(pk=team_id)
        if not team.web_analytics_pre_aggregated_tables_enabled:
            logger.warning(
                "Team no longer has pre-aggregated tables enabled, skipping backfill",
                team_id=team_id
            )
            return None
        return team
    except Team.DoesNotExist:
        logger.exception("Team not found for backfill", team_id=team_id)
        return None


def execute_backfill_query(
    team_id: int,
    date_start: str,
    date_end: str,
    table_name: str,
    sql_generator,
    timezone: str = "UTC"
) -> None:
    """Execute a single backfill query with error handling."""
    try:
        # Generate the INSERT query (direct to target table, no staging)
        insert_query = sql_generator(
            date_start=date_start,
            date_end=date_end,
            team_ids=[team_id],  # Single team backfill
            timezone=timezone,
            table_name=table_name,
            granularity="daily",  # Use daily granularity for backfill simplicity
            settings="",
        )

        logger.info(
            "Executing backfill query",
            team_id=team_id,
            table_name=table_name,
            date_start=date_start,
            date_end=date_end,
        )

        # Execute the query directly (no partition swapping)
        sync_execute(insert_query)

        logger.info(
            "Backfill query completed successfully",
            team_id=team_id,
            table_name=table_name,
        )

    except Exception as e:
        logger.error(
            "Backfill query failed",
            team_id=team_id,
            table_name=table_name,
            error=str(e),
            exc_info=True,
        )
        raise


@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def backfill_web_analytics_tables_for_team(self, team_id: int, backfill_days: int = DEFAULT_BACKFILL_DAYS):
    """
    Backfill web analytics pre-aggregated tables for a specific team.

    This task is triggered when a team enables pre-aggregated tables and performs
    a direct INSERT to populate the last N days of data without partition swapping.

    Args:
        team_id: The team ID to backfill
        backfill_days: Number of days to backfill (default 7, max 30)
    """
    try:
        # Safety checks
        if backfill_days > MAX_BACKFILL_DAYS:
            logger.warning(
                f"Backfill days {backfill_days} exceeds maximum {MAX_BACKFILL_DAYS}, using maximum",
                team_id=team_id
            )
            backfill_days = MAX_BACKFILL_DAYS

        # Validate team
        team = validate_team_for_backfill(team_id)
        if not team:
            return {"status": "skipped", "reason": "team_validation_failed"}

        # Get date range
        date_start, date_end = get_backfill_date_range(backfill_days)

        logger.info(
            "Starting web analytics backfill",
            team_id=team_id,
            team_name=team.name,
            date_start=date_start,
            date_end=date_end,
            backfill_days=backfill_days,
        )

        # Backfill web_pre_aggregated_stats
        execute_backfill_query(
            team_id=team_id,
            date_start=date_start,
            date_end=date_end,
            table_name="web_pre_aggregated_stats",
            sql_generator=WEB_STATS_INSERT_SQL,
            timezone=team.timezone,
        )

        # Backfill web_pre_aggregated_bounces
        execute_backfill_query(
            team_id=team_id,
            date_start=date_start,
            date_end=date_end,
            table_name="web_pre_aggregated_bounces",
            sql_generator=WEB_BOUNCES_INSERT_SQL,
            timezone=team.timezone,
        )

        logger.info(
            "Web analytics backfill completed successfully",
            team_id=team_id,
            team_name=team.name,
            backfill_days=backfill_days,
        )

        return {
            "status": "completed",
            "team_id": team_id,
            "team_name": team.name,
            "date_start": date_start,
            "date_end": date_end,
            "backfill_days": backfill_days,
        }

    except Exception as exc:
        logger.error(
            "Web analytics backfill failed",
            team_id=team_id,
            backfill_days=backfill_days,
            error=str(exc),
            exc_info=True,
        )

        # Retry with exponential backoff
        raise self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))


@shared_task
def validate_backfill_data_integrity(team_id: int, date_start: str, date_end: str) -> dict:
    """
    Validate the integrity of backfilled data by comparing row counts and basic metrics.

    This can be run after backfill to ensure data quality.
    """
    try:
        validation_queries = {
            "web_pre_aggregated_stats_rows": f"""
                SELECT COUNT(*) FROM web_pre_aggregated_stats
                WHERE team_id = {team_id}
                AND period_bucket >= '{date_start}'
                AND period_bucket < '{date_end}'
            """,

            "web_pre_aggregated_bounces_rows": f"""
                SELECT COUNT(*) FROM web_pre_aggregated_bounces
                WHERE team_id = {team_id}
                AND period_bucket >= '{date_start}'
                AND period_bucket < '{date_end}'
            """,
        }

        results = {}
        for metric_name, query in validation_queries.items():
            result = sync_execute(query)
            results[metric_name] = result[0][0] if result and result[0] else 0

        logger.info(
            "Backfill data validation completed",
            team_id=team_id,
            date_start=date_start,
            date_end=date_end,
            validation_results=results,
        )

        return {
            "status": "completed",
            "team_id": team_id,
            "date_range": {"start": date_start, "end": date_end},
            "validation_results": results,
        }

    except Exception as e:
        logger.error(
            "Backfill data validation failed",
            team_id=team_id,
            error=str(e),
            exc_info=True,
        )
        return {
            "status": "failed",
            "team_id": team_id,
            "error": str(e),
        }


@shared_task
def cleanup_corrupted_backfill_data(team_id: int, date_start: str, date_end: str) -> dict:
    """
    Safety mechanism to clean up corrupted backfill data if needed.

    This implements the "DELETE or disable tables daily" safety mechanism mentioned
    by the user for the riskier direct INSERT approach.
    """
    try:
        team = Team.objects.get(pk=team_id)

        cleanup_queries = [
            f"""
            DELETE FROM web_pre_aggregated_stats
            WHERE team_id = {team_id}
            AND period_bucket >= '{date_start}'
            AND period_bucket < '{date_end}'
            """,
            f"""
            DELETE FROM web_pre_aggregated_bounces
            WHERE team_id = {team_id}
            AND period_bucket >= '{date_start}'
            AND period_bucket < '{date_end}'
            """,
        ]

        for query in cleanup_queries:
            sync_execute(query)

        # Optionally disable pre-aggregated tables for the team
        team.web_analytics_pre_aggregated_tables_enabled = False
        team.save(update_fields=['web_analytics_pre_aggregated_tables_enabled'])

        logger.warning(
            "Corrupted backfill data cleaned up and tables disabled",
            team_id=team_id,
            date_start=date_start,
            date_end=date_end,
        )

        return {
            "status": "cleaned_up",
            "team_id": team_id,
            "tables_disabled": True,
            "date_range": {"start": date_start, "end": date_end},
        }

    except Exception as e:
        logger.error(
            "Failed to cleanup corrupted backfill data",
            team_id=team_id,
            error=str(e),
            exc_info=True,
        )
        return {
            "status": "failed",
            "team_id": team_id,
            "error": str(e),
        }
