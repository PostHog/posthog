from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    # CONCURRENTLY so the build takes no ACCESS EXCLUSIVE lock on posthog_cohort.
    # Concurrent builds can't run in a transaction, so this migration is non-atomic.
    atomic = False

    dependencies = [
        ("cohorts", "0012_cohortbackfillchunk_next_attempt_at_and_more"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="cohort",
            index=models.Index(
                fields=["team", "-created_at"],
                condition=models.Q(deleted=False),
                name="cohort_team_created_live_idx",
            ),
        ),
    ]
