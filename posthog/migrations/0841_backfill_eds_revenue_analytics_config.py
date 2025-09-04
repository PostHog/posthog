from django.db import migrations

import structlog

logger = structlog.get_logger(__name__)


def backfill_revenue_analytics_config(apps, schema_editor):
    ExternalDataSource = apps.get_model("posthog", "ExternalDataSource")
    ExternalDataSourceRevenueAnalyticsConfig = apps.get_model("posthog", "ExternalDataSourceRevenueAnalyticsConfig")

    for source in ExternalDataSource.objects.iterator(chunk_size=100):
        try:
            # Create or update the config
            ExternalDataSourceRevenueAnalyticsConfig.objects.update_or_create(
                external_data_source=source,
                defaults={
                    "enabled": source.revenue_analytics_enabled,
                    "include_invoiceless_charges": True,
                },
            )
            logger.info("revenue_config_migrated", source_id=source.id)
        except Exception as e:
            # If anything fails for a team, skip it and continue with others
            logger.error("revenue_config_migration_failed", source_id=source.id, error=str(e), exc_info=True)
            continue


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("posthog", "0840_externaldatasourcerevenueanalyticsconfig"),
    ]

    operations = [
        migrations.RunPython(backfill_revenue_analytics_config, reverse_code=migrations.RunPython.noop),
    ]
