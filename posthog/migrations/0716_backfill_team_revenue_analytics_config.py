from django.db import migrations

import structlog

logger = structlog.get_logger(__name__)


def backfill_revenue_analytics_config(apps, schema_editor):
    Team = apps.get_model("posthog", "Team")
    TeamRevenueAnalyticsConfig = apps.get_model("posthog", "TeamRevenueAnalyticsConfig")

    # Get all teams that have revenue_tracking_config
    teams_with_config = Team.objects.exclude(revenue_tracking_config__isnull=True).iterator()

    for team in teams_with_config:
        try:
            # Create or update the config
            TeamRevenueAnalyticsConfig.objects.update_or_create(
                team=team,
                defaults={
                    "base_currency": team.revenue_tracking_config.get("baseCurrency", "USD"),
                    "_events": team.revenue_tracking_config.get("events", []),
                },
            )
            logger.info("revenue_config_migrated", team_id=team.id)
        except Exception as e:
            # If anything fails for a team, skip it and continue with others
            logger.error("revenue_config_migration_failed", team_id=team.id, error=str(e), exc_info=True)
            continue


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("posthog", "0715_teamrevenueanalyticsconfig"),
    ]

    operations = [
        migrations.RunPython(backfill_revenue_analytics_config, reverse_code=migrations.RunPython.noop),
    ]
