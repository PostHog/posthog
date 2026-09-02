from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("cohorts", "0010_alter_cohortbackfillrun_marker_watch"),
    ]

    operations = [
        migrations.AddField(
            model_name="cohort",
            name="last_import_total_count",
            field=models.IntegerField(
                blank=True,
                null=True,
                help_text="Number of IDs supplied by the most recent static cohort import. Null if the cohort was never populated from a list of IDs.",
            ),
        ),
        migrations.AddField(
            model_name="cohort",
            name="last_import_unmatched_count",
            field=models.IntegerField(
                blank=True,
                null=True,
                help_text="How many of the IDs in the most recent static cohort import matched no person, and so were not added to the cohort.",
            ),
        ),
    ]
