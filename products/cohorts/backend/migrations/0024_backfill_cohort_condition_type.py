from django.db import migrations

import structlog

from products.cohorts.backend.models.cohort import Cohort as LiveCohort

logger = structlog.get_logger(__name__)

BATCH_SIZE = 1_000
LOG_EVERY_BATCHES = 25


def backfill_condition_type(apps, schema_editor):
    """Classify every cohort that has not been saved since `condition_type` was added.

    The flags service routes a realtime or behavioral cohort to its membership table only when
    `condition_type` marks a behavioral or lifecycle condition. A null value reads as "no behavioral
    condition", so such a cohort is evaluated from person properties and matches nobody. The value
    comes from the same classifier that `Cohort.save` and `resave_cohorts` use.
    """
    Cohort = apps.get_model("cohorts", "Cohort")
    db_alias = schema_editor.connection.alias
    unclassified = Cohort.objects.using(db_alias).filter(condition_type__isnull=True)

    last_id = 0
    batches = 0
    classified = 0
    while True:
        # Keyset pagination over the primary key, because a cohort without leaf conditions stays
        # null and would come back in every batch of a plain `IS NULL ... LIMIT` loop.
        batch = list(unclassified.filter(id__gt=last_id).order_by("id").only("id", "filters")[:BATCH_SIZE])
        if not batch:
            logger.info("cohort_condition_type_backfill_completed", batches=batches, classified=classified)
            return
        last_id = batch[-1].id

        changed = []
        for cohort in batch:
            # Old rows can hold filter shapes that no save has validated since. One that the
            # classifier cannot read stays null, because a raise here would stop the deploy.
            # `resave_cohorts` reports every gated cohort that is still null.
            try:
                cohort.condition_type = LiveCohort.compute_condition_type(cohort.filters)
            except Exception:
                logger.exception("cohort_condition_type_backfill_unreadable", cohort_id=cohort.id)
                continue
            if cohort.condition_type is not None:
                changed.append(cohort)
        # The `IS NULL` filter stays on the update, so a cohort that a save classified after this
        # batch was read keeps the value that the save computed from its newer filters.
        classified += unclassified.bulk_update(changed, ["condition_type"])

        batches += 1
        if batches % LOG_EVERY_BATCHES == 0:
            logger.info("cohort_condition_type_backfill_progress", batches=batches, classified=classified)


class Migration(migrations.Migration):
    # Each batch commits on its own, so the scan never holds row locks on every cohort at once.
    # The `IS NULL` filter makes a `bin/migrate` retry after a partial run continue where it stopped.
    atomic = False

    dependencies = [
        ("cohorts", "0023_turn_on_realtime_for_processed_teams"),
    ]

    operations = [
        migrations.RunPython(backfill_condition_type, migrations.RunPython.noop, elidable=True),
    ]
