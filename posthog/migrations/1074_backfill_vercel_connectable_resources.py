from django.db import migrations

import structlog

logger = structlog.get_logger(__name__)


def trigger_backfill(apps, schema_editor):
    from ee.api.vercel.tasks import backfill_vercel_connectable_resources

    # Enqueuing needs a live Celery broker connection, which can drop transiently at
    # migration time. This is a best-effort, one-shot, elidable backfill, so a broker
    # hiccup must never fail the schema migration — log and swallow instead.
    try:
        backfill_vercel_connectable_resources.delay()
    except Exception:
        logger.exception("Failed to enqueue backfill_vercel_connectable_resources during migration")


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1073_migrate_dashboards_models"),
    ]

    operations = [
        migrations.RunPython(trigger_backfill, migrations.RunPython.noop, elidable=True),
    ]
