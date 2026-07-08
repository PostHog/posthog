from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("posthog", "1237_alter_integration_kind")]

    operations = [
        migrations.AddField(
            model_name="ducklakebackfill",
            name="earliest_event_date",
            field=models.DateField(
                blank=True,
                help_text="Cached earliest event date (clamped to the backfill floor) used to size the historical "
                "backfill range. Populated lazily by the full-backfill sensor so it never re-queries ClickHouse; "
                "leave unset to have the sensor resolve and store it on its next tick.",
                null=True,
            ),
        ),
    ]
