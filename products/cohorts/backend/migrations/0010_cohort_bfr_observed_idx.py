from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently, SafeRemoveIndexConcurrently


class Migration(migrations.Migration):
    # CONCURRENTLY so neither the build nor the drop takes an ACCESS EXCLUSIVE lock on
    # cohort_backfill_runs. Concurrent index operations can't run in a transaction, so this
    # migration is non-atomic.
    atomic = False

    dependencies = [
        ("cohorts", "0009_cohort_backfill_per_kind_uniqueness"),
    ]

    # Add before drop, so the finalizer's discovery is never left without a usable index. Both
    # indexes are partial on status='reconciling', which keeps the transient duplicate small.
    operations = [
        SafeAddIndexConcurrently(
            model_name="cohortbackfillrun",
            index=models.Index(
                condition=models.Q(("status", "reconciling")),
                fields=["reconcile_observed_at", "backfill_kind"],
                name="cohort_bfr_observed_idx",
            ),
        ),
        SafeRemoveIndexConcurrently(
            model_name="cohortbackfillrun",
            name="cohort_bfr_reconciling_idx",
        ),
    ]
