from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("cohorts", "0004_cohort_backfill_tables"),
    ]

    operations = [
        migrations.AddField(
            model_name="cohort",
            name="condition_type",
            field=models.JSONField(
                blank=True,
                help_text=(
                    "Flags describing which kinds of conditions the cohort's filters contain: "
                    "person_properties (property or person_metadata), behavioral, lifecycle "
                    "(first-seen/regularly/stopped/restarted performing an event), and cohorts "
                    "(nested cohort references). Null when the cohort has no filters to classify."
                ),
                null=True,
            ),
        ),
    ]
