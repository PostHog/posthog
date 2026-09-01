from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    # CONCURRENTLY so the build takes no ACCESS EXCLUSIVE lock on the history table.
    # Concurrent builds can't run in a transaction, so this migration is non-atomic.
    atomic = False

    dependencies = [
        ("cohorts", "0012_cohortbackfillchunk_next_attempt_at_and_more"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="cohortcalculationhistory",
            index=models.Index(
                condition=models.Q(("error__isnull", False), models.Q(("error", ""), _negated=True)),
                fields=["cohort", "-started_at"],
                name="cohort_calc_hist_error_idx",
            ),
        ),
    ]
