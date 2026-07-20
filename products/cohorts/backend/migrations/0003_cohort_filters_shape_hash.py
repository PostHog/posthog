from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("cohorts", "0002_cohort_last_backfill_events_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="cohort",
            name="filters_shape_hash",
            field=models.CharField(blank=True, max_length=64, null=True),
        ),
        migrations.AddField(
            model_name="cohort",
            name="behavioral_filters_shape_hash",
            field=models.CharField(blank=True, max_length=64, null=True),
        ),
    ]
