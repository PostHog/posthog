from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("cohorts", "0015_cohortbackfillchunk_claimable_after_and_more"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="cohort",
            index=models.Index(
                fields=["created_at"],
                condition=models.Q(("deleted", False), ("is_calculating", True), ("is_static", True)),
                name="cohort_static_calculating_idx",
            ),
        ),
    ]
