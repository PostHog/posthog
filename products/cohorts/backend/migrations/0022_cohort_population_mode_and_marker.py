from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("cohorts", "0021_cohort_backfill_refusal"),
    ]

    operations = [
        migrations.AddField(
            model_name="cohort",
            name="pending_population_mode",
            field=models.CharField(
                blank=True,
                choices=[("append", "Append"), ("replace", "Replace")],
                help_text="How the claimed static population writes its matches: append adds them to the current members, and replace also removes the members the query no longer matches. Null if the cohort was never claimed for a population.",
                max_length=16,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="cohort",
            name="population_marker",
            field=models.DateTimeField(
                blank=True,
                help_text="ClickHouse _timestamp of the current replace attempt. Every attempt stores a newer value, and an attempt that finds a different value stored stops writing. Null when no replace is in flight.",
                null=True,
            ),
        ),
    ]
