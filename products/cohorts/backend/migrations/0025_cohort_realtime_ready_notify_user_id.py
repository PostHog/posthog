from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("cohorts", "0024_backfill_cohort_condition_type"),
    ]

    operations = [
        migrations.AddField(
            model_name="cohort",
            name="realtime_ready_notify_user_id",
            field=models.BigIntegerField(blank=True, null=True),
        ),
    ]
