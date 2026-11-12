"""The per-team cohort resave, shared by `resave_cohorts` and realtime cohort enablement.

It lives in core because it coalesces flags cache rebuilds, and the cohorts product cannot depend on
`products.feature_flags`.
"""

from __future__ import annotations

import signal
import threading
from collections.abc import Iterator, Sequence
from contextlib import AbstractContextManager, contextmanager, nullcontext
from types import FrameType
from typing import Any

import structlog

from posthog.api.cohort import validate_filters_and_compute_realtime_support
from posthog.dataclasses import frozen
from posthog.models.team.team import Team

from products.cohorts.backend.models.cohort import Cohort, CohortOrEmpty, CohortType
from products.cohorts.backend.models.util import (
    get_all_cohort_dependencies,
    legacy_groups_to_filters,
    sort_cohorts_topologically,
)
from products.feature_flags.backend.flags_cache import coalesced_cohort_flags_cache_rebuilds

logger = structlog.get_logger(__name__)

# The cohort types the realtime membership gate routes, so a null condition_type changes how they
# evaluate. See `uses_realtime_membership` in rust/feature-flags/src/cohorts/cohort_models.rs.
REALTIME_GATED_COHORT_TYPES = (CohortType.REALTIME, CohortType.BEHAVIORAL)

# The catchable signals that end a run without unwinding it. SIGTERM reaches the command when it
# is the container's main process or is killed by hand. A run in a toolbox `kubectl exec` shell
# never gets SIGTERM, because a pod stop signals only the main process, but a hangup of that
# shell's terminal ends it with SIGHUP.
UNWIND_SIGNALS = (signal.SIGTERM, signal.SIGHUP)


@contextmanager
def termination_unwinds() -> Iterator[bool]:
    """Raise on SIGTERM and SIGHUP instead of dying in place, when they are this process's to take.

    Either signal otherwise kills the process between a team's cohort saves committing and its
    coalesced cache rebuild being enqueued, and nothing sweeps that back: the service-cache
    verifier does not compare cohorts, and a rerun finds nothing left to change. Unwinding lets
    the coalescing block dispatch the teams it has already recorded. `KeyboardInterrupt` because
    the per-cohort `except Exception` must not swallow it. SIGKILL cannot be caught, so an
    expired toolbox claim or an OOM kill still loses the rebuild of the team in progress.

    Yields whether the unwind is in place. The admin view runs the command inside a web worker,
    which owns its own shutdown, so the caller must not coalesce rebuilds it cannot flush there.
    """
    if threading.current_thread() is not threading.main_thread():
        # Only the main thread may install a handler, and a server that hands sync views to a
        # threadpool runs the admin view off it.
        yield False
        return

    dispositions = {signum: signal.getsignal(signum) for signum in UNWIND_SIGNALS}
    if any(disposition not in (signal.SIG_DFL, signal.SIG_IGN) for disposition in dispositions.values()):
        # Something else owns one of them, a web worker serving the admin view for one. Taking it
        # over would replace that shutdown path, and a handler installed outside Python reads
        # back as `None`, which cannot be restored afterwards.
        yield False
        return

    def raise_interrupt(signum: int, frame: FrameType | None) -> None:
        raise KeyboardInterrupt(f"received {signal.Signals(signum).name}")

    # An ignored signal cannot end the run, so it stays ignored. `nohup` ignores SIGHUP, and a
    # run started under it must survive the hangup it asked to survive.
    taken = [signum for signum, disposition in dispositions.items() if disposition is signal.SIG_DFL]
    for signum in taken:
        signal.signal(signum, raise_interrupt)
    try:
        yield True
    finally:
        for signum in taken:
            signal.signal(signum, signal.SIG_DFL)


@frozen
class CohortResaveStats:
    total: int
    changed: int
    errors: int
    validation_errors: int
    prospective_realtime: int
    # The team's cohorts were resaved but its cache rebuild never reached the broker, so the
    # team keeps a stale flags cache.
    rebuild_dispatch_failed: bool


@frozen
class CohortResaveOutcome:
    changed: bool
    validation_failed: bool
    prospective_realtime: bool


UNTOUCHED_COHORT = CohortResaveOutcome(changed=False, validation_failed=False, prospective_realtime=False)


def unclassified_cohort_ids(team_ids: Sequence[int] | None) -> list[int]:
    """Cohorts the realtime gate routes that still have a null `condition_type`, read back from
    the database.

    Reading persisted state covers every way a cohort ends up unclassified: a save that raised, a
    filter set the validator rejected, and a well-formed filter group with no leaf conditions,
    which the resave classifies as realtime and leaves with a null `condition_type`. It only
    means anything after a run that persisted, so the caller skips it on a dry run.
    """
    qs = Cohort.objects.filter(cohort_type__in=REALTIME_GATED_COHORT_TYPES, condition_type__isnull=True)
    if team_ids is not None:
        qs = qs.filter(team_id__in=team_ids)
    return list(qs.order_by("id").values_list("id", flat=True))


def resave_team_cohorts(team: Team, *, batch_size: int, dry_run: bool, coalesce_rebuilds: bool) -> CohortResaveStats:
    """Process all cohorts for a single team."""
    all_cohorts = _load_team_cohorts(team, batch_size)
    # Convert groups-only cohorts up front so the dependency map, the sort, and the recompute
    # all read their filters. Static cohorts never evaluate filters, so they stay as they are.
    # A cohort whose groups can't be converted stays unfixed, so it counts as an error.
    unconvertible = 0
    for loaded in all_cohorts:
        if not loaded.filters and loaded.groups and not loaded.is_static:
            loaded.filters = legacy_groups_to_filters(loaded.groups)
            if not loaded.filters:
                unconvertible += 1
                logger.error("cohort_resave_groups_unconvertible", cohort_id=loaded.id, team_id=team.id)
    seen_cohorts_cache: dict[int, CohortOrEmpty] = {c.id: c for c in all_cohorts}
    cohort_dependencies, unreadable_ids = _build_dependency_map(team, all_cohorts, seen_cohorts_cache)

    # Sort cohorts topologically - dependencies first, then dependents. The sort parses the
    # filters of every cohort it reaches, so the unreadable ones stay out of it.
    sorted_cohort_ids = sort_cohorts_topologically(
        {c.id for c in all_cohorts if c.id not in unreadable_ids}, seen_cohorts_cache
    )

    total = len(unreadable_ids)
    changed = 0
    errors = len(unreadable_ids) + unconvertible
    validation_errors = 0
    prospective_realtime = 0

    # Each save fires two whole-team flags-cache rebuilds, so the block coalesces them into one
    # dispatch per team. Scoping it to one team means that team reads a stale cache only while
    # its own cohorts are being resaved, rather than until the whole run finishes. Without the
    # signal unwind nothing flushes the block on shutdown, so an unprotected run keeps the
    # per-save enqueues instead.
    rebuilds: AbstractContextManager[set[int]] = (
        coalesced_cohort_flags_cache_rebuilds() if coalesce_rebuilds else nullcontext(set())
    )
    with rebuilds as stale_cache_teams:
        for cohort_id in sorted_cohort_ids:
            cohort = seen_cohorts_cache.get(cohort_id)
            if not cohort:
                continue

            total += 1
            try:
                outcome = _recompute_cohort(cohort, team, seen_cohorts_cache, cohort_dependencies)
                if outcome.validation_failed:
                    validation_errors += 1
                # Counted before the save, so a realtime cohort whose save raises still reports as one.
                if outcome.prospective_realtime:
                    prospective_realtime += 1
                if outcome.changed:
                    if not dry_run:
                        cohort.save(update_fields=["filters", "cohort_type", "condition_type"])
                    changed += 1
            except Exception as err:
                errors += 1
                logger.error(
                    "cohort_resave_error",
                    cohort_id=cohort.id,
                    team_id=team.id,
                    error=str(err),
                    exc_info=True,
                )

    return CohortResaveStats(
        total=total,
        changed=changed,
        errors=errors,
        validation_errors=validation_errors,
        prospective_realtime=prospective_realtime,
        rebuild_dispatch_failed=bool(stale_cache_teams),
    )


def _load_team_cohorts(team: Team, batch_size: int) -> list[Cohort]:
    """Read every cohort on the team, one page at a time."""
    # No `select_related("team")`: the caller already holds the team object and passes it into
    # `_recompute_cohort`, so joining it in here would only hydrate the deprecated taxonomy
    # columns (which TOAST out to megabytes) onto every retained cohort row. The forward-FK
    # defer that `TeamManager` applies does not reach a `select_related` JOIN.
    base_qs = Cohort.objects.filter(team=team).order_by("id")
    all_cohorts: list[Cohort] = []
    last_id = 0

    while True:
        batch = list(base_qs.filter(id__gt=last_id)[:batch_size])
        if not batch:
            return all_cohorts
        all_cohorts.extend(batch)
        last_id = batch[-1].id


def _build_dependency_map(
    team: Team, all_cohorts: list[Cohort], seen_cohorts_cache: dict[int, CohortOrEmpty]
) -> tuple[dict[int, set[int]], set[int]]:
    """Map each cohort id to every cohort id it depends on, recursively: A->B->C makes A depend on
    both B and C.

    Also return the ids of the cohorts whose dependencies cannot be read. Malformed filters make
    the lookup raise for that cohort and for every cohort that references it. The run skips
    these cohorts and counts them as errors, so one bad cohort does not stop the run.
    """
    cohort_dependencies: dict[int, set[int]] = {}
    unreadable_ids: set[int] = set()
    for cohort in all_cohorts:
        if not cohort.filters:
            continue
        try:
            dependencies = get_all_cohort_dependencies(cohort, seen_cohorts_cache=seen_cohorts_cache)
        except Exception as err:
            unreadable_ids.add(cohort.id)
            logger.error(
                "cohort_resave_error",
                cohort_id=cohort.id,
                team_id=team.id,
                error=str(err),
                exc_info=True,
            )
            continue
        cohort_dependencies[cohort.id] = {dep.id for dep in dependencies}
    return cohort_dependencies, unreadable_ids


def _recompute_cohort(
    cohort: Cohort,
    team: Team,
    seen_cohorts_cache: dict[int, CohortOrEmpty],
    cohort_dependencies: dict[int, set[int]],
) -> CohortResaveOutcome:
    """Recompute one cohort's filters, cohort_type, and condition_type in memory.

    This only mutates the cohort in memory and returns the outcome; the caller persists the
    change and counts it.
    """
    filters = cohort.filters
    # Nothing to recompute without filters.
    if not filters:
        return UNTOUCHED_COHORT

    # Compute the new filters with inline bytecode and cohort_type
    # Use defensive validation with detailed error reporting
    clean_filters, computed_type, validation_error_list = validate_filters_and_compute_realtime_support(
        filters, team, current_cohort_type=cohort.cohort_type, cohort_count=cohort.count
    )

    # If validation failed but we got the original filters back, log the issue and skip
    if validation_error_list:
        logger.warning(
            "cohort_validation_skipped",
            cohort_id=cohort.id,
            team_id=cohort.team_id,
            reason="Invalid filter structure - keeping original filters",
        )
        return CohortResaveOutcome(changed=False, validation_failed=True, prospective_realtime=False)

    if computed_type == "realtime" and _references_block_realtime(filters, seen_cohorts_cache, cohort_dependencies):
        computed_type = None

    computed_condition_type = Cohort.compute_condition_type(clean_filters)

    # Decide if there is any change worth persisting/reporting
    will_change = (
        clean_filters != filters
        or computed_type != cohort.cohort_type
        or computed_condition_type != cohort.condition_type
    )

    # ALWAYS update in-memory for dependency checking
    cohort.filters = clean_filters
    cohort.cohort_type = computed_type
    cohort.condition_type = computed_condition_type

    return CohortResaveOutcome(
        changed=will_change,
        validation_failed=False,
        prospective_realtime=computed_type == "realtime",
    )


def _references_block_realtime(
    filters: dict[str, Any],
    seen_cohorts_cache: dict[int, CohortOrEmpty],
    cohort_dependencies: dict[int, set[int]],
) -> bool:
    """Whether a directly referenced cohort stops this one from evaluating in realtime."""
    for ref_id in _get_direct_cohort_references(filters):
        ref_cohort = seen_cohorts_cache.get(ref_id)
        if not ref_cohort:
            continue
        # Static cohorts cannot be realtime, so any cohort referencing them can't be realtime
        if ref_cohort.is_static:
            return True
        # Cohorts without filters (empty cohorts) can be considered realtime-compatible
        # since they match no one (always false)
        if not ref_cohort.filters:
            continue
        # If any directly referenced cohort has dependencies, this cannot be realtime
        if cohort_dependencies.get(ref_id):
            return True
        # Also check if the referenced cohort is not realtime
        if ref_cohort.cohort_type != "realtime":
            return True
    return False


def _get_direct_cohort_references(filters: dict[str, Any]) -> set[int]:
    """Get only the direct cohort references from filters (not transitive)."""
    referenced_ids = set()

    if isinstance(filters, dict):
        properties = filters.get("properties", {})
        if isinstance(properties, dict):
            values = properties.get("values", [])
            if isinstance(values, list):
                for value in values:
                    if isinstance(value, dict):
                        if value.get("type") == "cohort" and value.get("value"):
                            try:
                                referenced_ids.add(int(value["value"]))
                            except (ValueError, TypeError):
                                pass
                        # Recursively check nested groups
                        if "values" in value:
                            referenced_ids.update(_get_direct_cohort_references({"properties": value}))

    return referenced_ids
