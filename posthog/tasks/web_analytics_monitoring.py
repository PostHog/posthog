from datetime import datetime, timedelta
from typing import Dict, List, Optional

import structlog
from celery import shared_task
from django.conf import settings

from posthog.clickhouse.client import sync_execute
from posthog.models.team.team import Team
from posthog.tasks.utils import CeleryQueue

logger = structlog.get_logger(__name__)


@shared_task(queue=CeleryQueue.PERIODIC.value)
def monitor_web_analytics_backfill_health():
    """
    Periodic task to monitor the health of web analytics backfill system.
    
    This task runs daily to:
    1. Check for teams that enabled pre-aggregated tables but have no data
    2. Detect missing data gaps that might indicate failed backfills  
    3. Generate alerts for intervention
    """
    try:
        logger.info("Starting web analytics backfill health check")
        
        health_report = {
            "timestamp": datetime.utcnow().isoformat(),
            "enabled_teams": 0,
            "teams_with_data": 0,
            "teams_missing_data": [],
            "data_gaps_detected": [],
            "recommendations": [],
        }
        
        # Get all teams with pre-aggregated tables enabled
        enabled_teams = Team.objects.filter(web_analytics_pre_aggregated_tables_enabled=True)
        health_report["enabled_teams"] = enabled_teams.count()
        
        if health_report["enabled_teams"] == 0:
            logger.info("No teams have web analytics pre-aggregated tables enabled")
            return health_report
        
        # Check each team for data presence
        for team in enabled_teams:
            data_check = check_team_data_health(team.id)
            
            if data_check["has_recent_data"]:
                health_report["teams_with_data"] += 1
            else:
                health_report["teams_missing_data"].append({
                    "team_id": team.id,
                    "team_name": team.name,
                    "organization": team.organization.name,
                    "enabled_date": team.updated_at.isoformat() if team.updated_at else None,
                    "issue": data_check["issue"],
                })
        
        # Generate recommendations
        if health_report["teams_missing_data"]:
            health_report["recommendations"].append(
                f"Consider running manual backfill for {len(health_report['teams_missing_data'])} teams with missing data"
            )
        
        # Log summary
        logger.info(
            "Web analytics backfill health check completed",
            enabled_teams=health_report["enabled_teams"],
            teams_with_data=health_report["teams_with_data"],
            teams_missing_data=len(health_report["teams_missing_data"]),
        )
        
        # Send alerts if issues detected
        if health_report["teams_missing_data"]:
            send_backfill_health_alert(health_report)
        
        return health_report
        
    except Exception as e:
        logger.error(
            "Web analytics backfill health check failed",
            error=str(e),
            exc_info=True,
        )
        return {"status": "error", "error": str(e)}


def check_team_data_health(team_id: int, lookback_days: int = 3) -> Dict:
    """
    Check if a team has recent data in pre-aggregated tables.
    
    Args:
        team_id: Team ID to check
        lookback_days: Number of recent days to check for data
        
    Returns:
        Dict with health status and details
    """
    try:
        # Check for data in the last N days
        cutoff_date = (datetime.utcnow() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
        
        stats_query = f"""
        SELECT COUNT(*) as row_count
        FROM web_pre_aggregated_stats 
        WHERE team_id = {team_id} 
        AND period_bucket >= '{cutoff_date}'
        """
        
        bounces_query = f"""
        SELECT COUNT(*) as row_count
        FROM web_pre_aggregated_bounces 
        WHERE team_id = {team_id} 
        AND period_bucket >= '{cutoff_date}'
        """
        
        stats_result = sync_execute(stats_query)
        bounces_result = sync_execute(bounces_query)
        
        stats_count = stats_result[0][0] if stats_result and stats_result[0] else 0
        bounces_count = bounces_result[0][0] if bounces_result and bounces_result[0] else 0
        
        has_recent_data = stats_count > 0 and bounces_count > 0
        
        return {
            "team_id": team_id,
            "has_recent_data": has_recent_data,
            "stats_rows": stats_count,
            "bounces_rows": bounces_count,
            "lookback_days": lookback_days,
            "issue": None if has_recent_data else f"No data found in last {lookback_days} days",
        }
        
    except Exception as e:
        logger.error(
            "Failed to check team data health",
            team_id=team_id,
            error=str(e),
            exc_info=True,
        )
        return {
            "team_id": team_id,
            "has_recent_data": False,
            "issue": f"Health check failed: {str(e)}",
        }


def send_backfill_health_alert(health_report: Dict):
    """
    Send alert about backfill health issues.
    
    This could integrate with Slack, email, or PostHog's internal alerting system.
    """
    try:
        missing_teams = health_report.get("teams_missing_data", [])
        if not missing_teams:
            return
        
        alert_message = f"""
🚨 Web Analytics Backfill Health Alert

{len(missing_teams)} teams have missing pre-aggregated data:

"""
        
        for team_info in missing_teams[:10]:  # Limit to first 10 for readability
            alert_message += f"• Team {team_info['team_id']} ({team_info['team_name']}): {team_info['issue']}\n"
        
        if len(missing_teams) > 10:
            alert_message += f"\n... and {len(missing_teams) - 10} more teams\n"
        
        alert_message += f"""
Recommendations:
{chr(10).join(f'• {rec}' for rec in health_report.get('recommendations', []))}

Use: python manage.py backfill_web_analytics list
     python manage.py backfill_web_analytics backfill --team-id <ID> --async
"""
        
        logger.warning(
            "Web analytics backfill health alert",
            alert_message=alert_message.strip(),
            teams_affected=len(missing_teams),
        )
        
        # TODO: Integrate with actual alerting system (Slack, email, etc.)
        # For now, just log at WARNING level which should be picked up by monitoring
        
    except Exception as e:
        logger.error(
            "Failed to send backfill health alert",
            error=str(e),
            exc_info=True,
        )


@shared_task
def generate_backfill_metrics_report(days: int = 7) -> Dict:
    """
    Generate metrics report for web analytics backfill performance.
    
    This can be used for dashboards and monitoring of the backfill system.
    """
    try:
        logger.info(f"Generating backfill metrics report for last {days} days")
        
        cutoff_date = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")
        
        # Get aggregate metrics across all teams
        metrics_queries = {
            "total_teams_enabled": """
                SELECT COUNT(*) FROM posthog_team 
                WHERE web_analytics_pre_aggregated_tables_enabled = true
            """,
            
            "total_stats_rows": f"""
                SELECT COUNT(*) FROM web_pre_aggregated_stats 
                WHERE period_bucket >= '{cutoff_date}'
            """,
            
            "total_bounces_rows": f"""
                SELECT COUNT(*) FROM web_pre_aggregated_bounces 
                WHERE period_bucket >= '{cutoff_date}'
            """,
            
            "active_teams_with_data": f"""
                SELECT COUNT(DISTINCT team_id) FROM web_pre_aggregated_stats 
                WHERE period_bucket >= '{cutoff_date}'
            """,
        }
        
        report = {
            "timestamp": datetime.utcnow().isoformat(),
            "period_days": days,
            "metrics": {},
        }
        
        for metric_name, query in metrics_queries.items():
            try:
                result = sync_execute(query)
                report["metrics"][metric_name] = result[0][0] if result and result[0] else 0
            except Exception as e:
                logger.error(f"Failed to execute query for {metric_name}", error=str(e))
                report["metrics"][metric_name] = None
        
        # Calculate derived metrics
        if report["metrics"]["total_teams_enabled"] and report["metrics"]["active_teams_with_data"]:
            report["metrics"]["data_coverage_percentage"] = round(
                (report["metrics"]["active_teams_with_data"] / report["metrics"]["total_teams_enabled"]) * 100, 2
            )
        
        logger.info(
            "Backfill metrics report generated",
            total_teams_enabled=report["metrics"]["total_teams_enabled"],
            active_teams_with_data=report["metrics"]["active_teams_with_data"],
            data_coverage_percentage=report["metrics"].get("data_coverage_percentage", "N/A"),
        )
        
        return report
        
    except Exception as e:
        logger.error(
            "Failed to generate backfill metrics report",
            error=str(e),
            exc_info=True,
        )
        return {"status": "error", "error": str(e)}