from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("cohorts", "0004_cohort_backfill_tables"),
    ]

    operations = [
        migrations.AddField(
            model_name="cohort",
            name="condition_type",
            field=models.CharField(
                blank=True,
                choices=[
                    ("property_only", "property_only"),
                    ("behavioral_only", "behavioral_only"),
                    ("both", "both"),
                ],
                help_text=(
                    "Whether the cohort's filters are property-only, behavioral-only, or contain both. "
                    "Null when neither is present, e.g. empty filters or a cohort made up only of nested "
                    "cohort references."
                ),
                max_length=50,
                null=True,
            ),
        ),
    ]
