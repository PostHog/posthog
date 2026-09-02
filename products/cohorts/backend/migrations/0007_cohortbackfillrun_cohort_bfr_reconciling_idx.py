from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    # CONCURRENTLY so the build takes no ACCESS EXCLUSIVE lock on cohort_backfill_runs.
    # Concurrent builds can't run in a transaction, so this migration is non-atomic.
    atomic = False

    dependencies = [
        ("cohorts", "0006_cohort_backfill_completion"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="cohortbackfillrun",
            index=models.Index(
                condition=models.Q(("status", "reconciling")),
                fields=["backfill_kind", "reconcile_observed_at"],
                name="cohort_bfr_reconciling_idx",
            ),
        ),
    ]
