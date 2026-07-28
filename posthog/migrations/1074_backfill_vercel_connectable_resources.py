from django.db import migrations

import structlog

logger = structlog.get_logger(__name__)


def trigger_backfill(apps, schema_editor):
    from ee.api.vercel.tasks import backfill_vercel_connectable_resources

    try:
        backfill_vercel_connectable_resources.delay()
    except Exception:
        # Dispatching to the Celery broker (Redis) must not fail the migration — a
        # transient broker outage would otherwise wedge the deploy's migrate step.
        # The one-shot backfill can be re-run out of band if this dispatch is dropped.
        logger.warning("vercel_connectable_backfill_dispatch_failed", exc_info=True)


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1073_migrate_dashboards_models"),
    ]

    operations = [
        migrations.RunPython(trigger_backfill, migrations.RunPython.noop, elidable=True),
    ]
