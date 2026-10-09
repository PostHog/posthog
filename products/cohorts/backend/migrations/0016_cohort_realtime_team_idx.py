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
                condition=models.Q(cohort_type="realtime", deleted=False, filters__isnull=False),
                fields=["team"],
                name="cohort_realtime_team_idx",
            ),
        ),
    ]
