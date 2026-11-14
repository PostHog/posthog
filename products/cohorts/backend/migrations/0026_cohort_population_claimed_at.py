from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("cohorts", "0025_cohortcalculationhistory_mode"),
    ]

    operations = [
        migrations.AddField(
            model_name="cohort",
            name="population_claimed_at",
            field=models.DateTimeField(
                blank=True,
                help_text="When the current static population was requested. A replace keeps the members added at or after this time. Null when no population is pending.",
                null=True,
            ),
        ),
    ]
