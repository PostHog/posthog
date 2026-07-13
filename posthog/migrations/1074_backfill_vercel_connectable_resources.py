from django.db import migrations

import structlog

logger = structlog.get_logger(__name__)


def trigger_backfill(apps, schema_editor):
    from ee.api.vercel.tasks import backfill_vercel_connectable_resources

    # Enqueuing hits the Celery broker, so a transient broker outage would otherwise
    # abort the migration and block the deploy. This backfill is a best-effort one-shot,
    # so swallow enqueue failures and let the schema migration finish.
    try:
        backfill_vercel_connectable_resources.delay()
    except Exception:
        logger.exception("Failed to enqueue backfill_vercel_connectable_resources; skipping")


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1073_migrate_dashboards_models"),
    ]

    operations = [
        migrations.RunPython(trigger_backfill, migrations.RunPython.noop, elidable=True),
    ]
