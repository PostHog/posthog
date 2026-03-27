from django.db import migrations


def trigger_backfill(apps, schema_editor):
    from ee.api.vercel.tasks import backfill_vercel_connectable_resources

    backfill_vercel_connectable_resources.delay()


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1072_backfill_condition_aggregation"),
    ]

    operations = [
        migrations.RunPython(trigger_backfill, migrations.RunPython.noop, elidable=True),
    ]
