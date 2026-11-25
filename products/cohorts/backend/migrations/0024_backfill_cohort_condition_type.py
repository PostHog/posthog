import threading

from django.conf import settings
from django.db import migrations

import structlog

logger = structlog.get_logger(__name__)

BATCH_SIZE = 1_000
LOG_EVERY_BATCHES = 25
REFRESH_DEADLINE_SECONDS = 60
ROUTED_COHORT_TYPES = ("realtime", "behavioral")
READINESS_STAMPS = (
    "last_backfill_events_at",
    "last_backfill_person_properties_at",
    "last_realtime_cohort_calculation_at",
)


def _flags_routing_can_change(cohort) -> bool:
    """Whether the new value can move this cohort onto the flags service's membership table path."""
    return (
        cohort.cohort_type in ROUTED_COHORT_TYPES
        and not cohort.is_static
        and not cohort.deleted
        and any(getattr(cohort, stamp) is not None for stamp in READINESS_STAMPS)
        and (cohort.condition_type["behavioral"] or cohort.condition_type["lifecycle"])
    )


def _refresh_flags_caches(team_ids: set[int]) -> tuple[set[int], bool]:
    """Return the teams whose refresh was dispatched, and whether the deadline passed first."""
    # The flags service reads cohorts from the team's flags cache, and `bulk_update` fires none of the
    # cohort save receivers that rebuild it. Without the flags cache there is nothing to rebuild, and
    # an unreachable broker could stall the deploy, so this follows the save receiver's guard.
    if not settings.FLAGS_REDIS_URL:
        return set(), False
    from products.cohorts.backend.backfill.finalize import refresh_readiness_caches

    dispatched: list[int] = []

    def refresh_all() -> None:
        for team_id in sorted(team_ids):
            try:
                refresh_readiness_caches(team_id)
            except Exception:
                # The cache entry still refreshes before it expires, so a failed dispatch only delays the change.
                logger.exception("cohort_condition_type_backfill_cache_refresh_failed", team_id=team_id)
            else:
                dispatched.append(team_id)

    # Neither the default Django cache nor the Celery Redis transport sets a socket timeout, so a Redis
    # that accepts connections and never answers blocks a refresh forever. The daemon thread lets the
    # migration continue past that hang, and the process exit ends the blocked thread.
    worker = threading.Thread(target=refresh_all, daemon=True)
    worker.start()
    worker.join(REFRESH_DEADLINE_SECONDS)
    return set(dispatched), worker.is_alive()


def backfill_condition_type(apps, schema_editor):
    """Classify every cohort that has not been saved since `condition_type` was added.

    The flags service routes a realtime or behavioral cohort to its membership table only when
    `condition_type` marks a behavioral or lifecycle condition. A null value reads as "no behavioral
    condition", so such a cohort is evaluated from person properties and matches nobody. The value
    comes from the same classifier that `Cohort.save` and `resave_cohorts` use.
    """
    from products.cohorts.backend.models.cohort import Cohort as LiveCohort

    Cohort = apps.get_model("cohorts", "Cohort")
    db_alias = schema_editor.connection.alias
    unclassified = Cohort.objects.using(db_alias).filter(condition_type__isnull=True)
    fields = ("id", "team_id", "filters", "cohort_type", "is_static", "deleted", *READINESS_STAMPS)

    last_id = 0
    batches = 0
    classified = 0
    refreshes = 0
    refresh_stalled = False
    unrefreshed_team_ids: set[int] = set()
    while True:
        # Keyset pagination over the primary key, because a cohort without leaf conditions stays
        # null and would come back in every batch of a plain `IS NULL ... LIMIT` loop.
        batch = list(unclassified.filter(id__gt=last_id).order_by("id").only(*fields)[:BATCH_SIZE])
        if not batch:
            logger.info(
                "cohort_condition_type_backfill_completed",
                batches=batches,
                classified=classified,
                refreshes=refreshes,
                refresh_stalled=refresh_stalled,
                unrefreshed_team_ids=sorted(unrefreshed_team_ids),
            )
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

        # Refreshed after every batch, even for a team an earlier batch refreshed: a rebuild that ran
        # between the two batches read this batch's rows while they were still null. Refreshing per
        # batch also covers a retry after a partial run, which finds these rows classified.
        teams = {cohort.team_id for cohort in changed if _flags_routing_can_change(cohort)}
        if teams and refresh_stalled:
            unrefreshed_team_ids |= teams
        elif teams:
            dispatched, stalled = _refresh_flags_caches(teams)
            refreshes += len(dispatched)
            if stalled:
                # Later refreshes would wait on the same unresponsive Redis. The skipped teams pick up
                # the new value when their cache entries expire.
                refresh_stalled = True
                unrefreshed_team_ids |= teams - dispatched
                logger.warning("cohort_condition_type_backfill_cache_refresh_stalled", batch=batches + 1)

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
