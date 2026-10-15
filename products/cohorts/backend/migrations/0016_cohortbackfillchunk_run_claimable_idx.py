from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("cohorts", "0015_cohortbackfillchunk_claimable_after_and_more"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="cohortbackfillchunk",
            index=models.Index(
                condition=models.Q(("claimable_after__isnull", False)),
                fields=["run", "claimable_after"],
                name="cohort_bfc_run_claimable_idx",
            ),
        ),
    ]
