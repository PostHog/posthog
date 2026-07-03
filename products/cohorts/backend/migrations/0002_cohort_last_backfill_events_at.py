from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("cohorts", "0001_migrate_cohorts_models"),
    ]

    operations = [
        migrations.AddField(
            model_name="cohort",
            name="last_backfill_events_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
