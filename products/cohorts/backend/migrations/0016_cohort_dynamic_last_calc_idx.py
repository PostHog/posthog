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
                models.F("is_calculating"),
                models.OrderBy(models.F("last_calculation"), nulls_first=True),
                condition=models.Q(("deleted", False), ("is_static", False)),
                name="cohort_dynamic_last_calc_idx",
            ),
        ),
    ]
