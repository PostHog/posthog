from datetime import datetime, timedelta

import structlog
from celery import shared_task

from posthog.clickhouse.client import sync_execute
from posthog.models.team.team import Team
from posthog.models.web_preaggregated.sql import WEB_STATS_INSERT_SQL, WEB_BOUNCES_INSERT_SQL

logger = structlog.get_logger(__name__)

# Backfill configuration
DEFAULT_BACKFILL_DAYS = 7
MAX_BACKFILL_DAYS = 30  # Safety limit
BACKFILL_BATCH_SIZE = 5  # Teams to process per batch


def get_backfill_date_range(days: int = DEFAULT_BACKFILL_DAYS) -> tuple[str, str]:
    """Get the date range for backfill (last N days)."""
    end_date = datetime.utcnow()
    start_date = end_date - timedelta(days=days)

    return (
        start_date.strftime("%Y-%m-%d"),
        end_date.strftime("%Y-%m-%d")
    )


def get_teams_needing_backfill(limit: int = BACKFILL_BATCH_SIZE) -> list[int]:
    """
    Get teams that have pre-aggregated tables enabled but may be missing recent data.

    This is a simplified approach that targets teams with the setting enabled.
    A more sophisticated version would check for actual missing data.
    """
    teams = Team.objects.filter(
        web_analytics_pre_aggregated_tables_enabled=True
    ).values_list('id', flat=True)[:limit]

    return list(teams)


def check_team_has_recent_data(team_id: int, date_start: str) -> bool:
    """Check if team already has recent data in pre-aggregated tables."""
    try:
        query = f"""
            SELECT COUNT(*) FROM web_pre_aggregated_stats
            WHERE team_id = {team_id}
            AND period_bucket >= '{date_start}'
        """
        result = sync_execute(query)
        count = result[0][0] if result and result[0] else 0

        logger.info(
            "Checked existing data for team",
            team_id=team_id,
            date_start=date_start,
            existing_rows=count
        )

        # If we have some data, consider backfill not needed
        # This is a simple heuristic - could be more sophisticated
        return count > 0

    except Exception as e:
        logger.warning(
            "Failed to check existing data for team",
            team_id=team_id,
            error=str(e)
        )
        # On error, assume we need backfill to be safe
        return False


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
        # Generate the INSERT query (direct to target table)
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

        # Execute the query directly
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


def backfill_team(team_id: int, backfill_days: int = DEFAULT_BACKFILL_DAYS) -> dict:
    """Backfill a single team's web analytics data."""
    try:
        # Validate team exists and has pre-aggregated tables enabled
        try:
            team = Team.objects.get(
                pk=team_id,
                web_analytics_pre_aggregated_tables_enabled=True
            )
        except Team.DoesNotExist:
            logger.info(
                "Team not found or pre-aggregated tables disabled",
                team_id=team_id
            )
            return {"status": "skipped", "reason": "team_not_eligible"}

        # Get date range
        date_start, date_end = get_backfill_date_range(backfill_days)

        # Check if team already has recent data
        if check_team_has_recent_data(team_id, date_start):
            logger.info(
                "Team already has recent data, skipping backfill",
                team_id=team_id,
                date_start=date_start
            )
            return {"status": "skipped", "reason": "has_recent_data"}

        logger.info(
            "Starting scheduled backfill for team",
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
            "Scheduled backfill completed successfully",
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

    except Exception as e:
        logger.error(
            "Scheduled backfill failed for team",
            team_id=team_id,
            backfill_days=backfill_days,
            error=str(e),
            exc_info=True,
        )
        return {
            "status": "failed",
            "team_id": team_id,
            "error": str(e),
        }


@shared_task(bind=True, max_retries=2, default_retry_delay=300)
def process_backfill_batch(self, team_ids: list[int], backfill_days: int = DEFAULT_BACKFILL_DAYS):
    """Process a batch of teams for backfill."""
    if not team_ids:
        return {"status": "skipped", "reason": "no_teams"}

    logger.info(
        "Starting scheduled backfill batch",
        team_ids=team_ids,
        batch_size=len(team_ids),
        backfill_days=backfill_days
    )

    results = []
    for team_id in team_ids:
        try:
            result = backfill_team(team_id, backfill_days)
            results.append(result)
        except Exception as e:
            logger.error(
                "Failed to backfill team in batch",
                team_id=team_id,
                error=str(e),
                exc_info=True
            )
            results.append({
                "status": "failed",
                "team_id": team_id,
                "error": str(e)
            })

    # Summary
    completed = sum(1 for r in results if r["status"] == "completed")
    skipped = sum(1 for r in results if r["status"] == "skipped")
    failed = sum(1 for r in results if r["status"] == "failed")

    logger.info(
        "Scheduled backfill batch completed",
        total_teams=len(team_ids),
        completed=completed,
        skipped=skipped,
        failed=failed
    )

    return {
        "status": "batch_completed",
        "total_teams": len(team_ids),
        "completed": completed,
        "skipped": skipped,
        "failed": failed,
        "results": results
    }


@shared_task(bind=True, max_retries=1, default_retry_delay=600)
def discover_and_backfill_teams(self, backfill_days: int = DEFAULT_BACKFILL_DAYS):
    """
    Main scheduled task that discovers teams needing backfill and processes them.

    This should be run daily/hourly on a schedule to ensure teams with
    pre-aggregated tables enabled have recent data.
    """
    try:
        logger.info("Starting scheduled web analytics backfill discovery")

        # Safety limit
        if backfill_days > MAX_BACKFILL_DAYS:
            logger.warning(
                f"Backfill days {backfill_days} exceeds maximum {MAX_BACKFILL_DAYS}, using maximum"
            )
            backfill_days = MAX_BACKFILL_DAYS

        # Get teams that might need backfill
        team_ids = get_teams_needing_backfill(limit=BACKFILL_BATCH_SIZE)

        if not team_ids:
            logger.info("No teams found needing backfill")
            return {"status": "no_teams_found"}

        logger.info(
            "Found teams for potential backfill",
            team_count=len(team_ids),
            team_ids=team_ids
        )

        # Process the batch
        result = process_backfill_batch(team_ids, backfill_days)

        logger.info(
            "Scheduled backfill discovery completed",
            result=result
        )

        return result

    except Exception as exc:
        logger.error(
            "Scheduled backfill discovery failed",
            error=str(exc),
            exc_info=True,
        )

        # Retry with exponential backoff
        raise self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))

