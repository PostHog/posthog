from __future__ import annotations

import signal
import threading
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager, nullcontext
from types import FrameType
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

import structlog

from posthog.api.cohort import validate_filters_and_compute_realtime_support
from posthog.dataclasses import frozen
from posthog.models.team.team import Team

from products.cohorts.backend.models.cohort import Cohort, CohortType
from products.cohorts.backend.models.util import get_all_cohort_dependencies, sort_cohorts_topologically
from products.cohorts.backend.realtime_teams import is_realtime_cohort_team, realtime_allowlist_matches_every_team
from products.feature_flags.backend.flags_cache import coalesced_cohort_flags_cache_rebuilds

logger = structlog.get_logger(__name__)

# How many ids to name in a failure message before summarizing the rest.
ID_REPORT_LIMIT = 20

# The cohort types the realtime membership gate routes, so a null condition_type changes how they
# evaluate. See `uses_realtime_membership` in rust/feature-flags/src/cohorts/cohort_models.rs.
REALTIME_GATED_COHORT_TYPES = (CohortType.REALTIME, CohortType.BEHAVIORAL)


@contextmanager
def sigterm_unwinds() -> Iterator[bool]:
    """Raise on SIGTERM instead of dying in place, when SIGTERM is this command's to take.

    A pod roll otherwise kills the process between a team's cohort saves committing and its
    coalesced cache rebuild being enqueued, and nothing sweeps that back: the service-cache
    verifier does not compare cohorts, and a rerun finds nothing left to change. Unwinding lets
    the coalescing block dispatch the teams it has already recorded. `KeyboardInterrupt` because
    the per-cohort `except Exception` must not swallow it.

    Yields whether the unwind is in place. The admin view runs the command inside a web worker,
    which owns its own shutdown, so the caller must not coalesce rebuilds it cannot flush there.
    """
    if threading.current_thread() is not threading.main_thread():
        # Only the main thread may install a handler, and a server that hands sync views to a
        # threadpool runs the admin view off it.
        yield False
        return

    if signal.getsignal(signal.SIGTERM) is not signal.SIG_DFL:
        # Something else owns SIGTERM, a web worker serving the admin view for one. Taking it
        # over would replace that shutdown path, and a handler installed outside Python reads
        # back as `None`, which cannot be restored afterwards.
        yield False
        return

    def raise_interrupt(signum: int, frame: FrameType | None) -> None:
        raise KeyboardInterrupt("received SIGTERM")

    signal.signal(signal.SIGTERM, raise_interrupt)
    try:
        yield True
    finally:
        signal.signal(signal.SIGTERM, signal.SIG_DFL)


def _summarize_ids(ids: list[int]) -> str:
    shown = ", ".join(str(value) for value in ids[:ID_REPORT_LIMIT])
    remainder = len(ids) - ID_REPORT_LIMIT
    if remainder > 0:
        shown += f", and {remainder} more"
    return shown


class IncompleteResaveError(CommandError):
    """The run finished and persisted its saves, but left state a rerun does not repair.

    Distinct from the other `CommandError`s the command raises, which all reject the invocation
    before any work happens, so a caller can tell a run that never started from one that did.
    """


class UnclassifiedCohortsError(IncompleteResaveError):
    """The run left cohorts the realtime gate misreads."""


class StaleFlagsCacheError(IncompleteResaveError):
    """The run left teams whose flags cache rebuild never reached the broker."""


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
class TeamSelection:
    team_ids: tuple[int, ...] | None
    label: str
    # Whether the operator named a scope. Only then is an unclassified cohort worth failing on: a
    # bare run covers every team, including the ones the realtime gate never reads.
    explicit: bool


class Command(BaseCommand):
    help = "Regenerate inline bytecode (in filters), cohort_type, and condition_type for cohorts."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--team-id",
            type=int,
            nargs="+",
            help="Team IDs to process; if omitted, processes all teams.",
        )
        parser.add_argument(
            "--realtime-allowlist",
            action="store_true",
            help="Process the teams matched by REALTIME_COHORT_TEAM_ALLOWLIST.",
        )
        parser.add_argument(
            "--batch-size",
            default=500,
            type=int,
            help="Number of cohorts to fetch at once (for pagination).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Simulates the changes without persisting them to the database.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        # Parse CLI arguments
        selection = self._resolve_teams(options)
        dry_run: bool = bool(options.get("dry_run"))
        batch_size: int = int(options.get("batch_size") or 500)

        # Log start of operation
        logger.info(
            "cohort_resave_started",
            team_ids=selection.team_ids,
            dry_run=dry_run,
            batch_size=batch_size,
            scope=selection.label,
        )
        dry_run_label = " (dry run)" if dry_run else ""
        self.stdout.write(f"Starting cohort resave for {selection.label}, batch_size={batch_size}{dry_run_label}")

        # Get teams to process
        teams_qs = Team.objects.all().order_by("id")
        if selection.team_ids is not None:
            teams_qs = teams_qs.filter(id__in=selection.team_ids)

        # Track global stats
        global_total = 0
        global_changed = 0
        global_errors = 0
        global_validation_errors = 0
        global_prospective_realtime = 0
        stale_cache_team_ids: list[int] = []
        teams_processed = 0
        total_teams = teams_qs.count()

        # Process each team separately
        with sigterm_unwinds() as coalesce_rebuilds:
            for team in teams_qs:
                teams_processed += 1
                logger.info(
                    "cohort_resave_team_started",
                    team_id=team.id,
                    team_progress=f"{teams_processed}/{total_teams}",
                )
                self.stdout.write(f"Processing team {team.id} ({teams_processed}/{total_teams})")

                stats = self._process_team_cohorts(team, batch_size, dry_run, coalesce_rebuilds)

                # Accumulate stats
                global_total += stats.total
                global_changed += stats.changed
                global_errors += stats.errors
                global_validation_errors += stats.validation_errors
                global_prospective_realtime += stats.prospective_realtime
                if stats.rebuild_dispatch_failed:
                    stale_cache_team_ids.append(team.id)

                # Log team completion
                if stats.total > 0:
                    logger.info(
                        "cohort_resave_team_completed",
                        team_id=team.id,
                        total_cohorts=stats.total,
                        changed_cohorts=stats.changed,
                        realtime_cohorts=stats.prospective_realtime,
                        error_count=stats.errors,
                        validation_error_count=stats.validation_errors,
                        rebuild_dispatch_failed=stats.rebuild_dispatch_failed,
                        dry_run=dry_run,
                    )
                    msg = f"  Team {team.id}: {stats.total} cohorts, {stats.changed} changed, {stats.prospective_realtime} realtime"
                    if stats.errors > 0:
                        msg += f", {stats.errors} errors"
                    if stats.validation_errors > 0:
                        msg += f", {stats.validation_errors} validation errors"
                    if stats.rebuild_dispatch_failed:
                        msg += ", flags cache rebuild not enqueued"
                    unhealthy = stats.errors > 0 or stats.validation_errors > 0 or stats.rebuild_dispatch_failed
                    self.stdout.write((self.style.WARNING if unhealthy else self.style.SUCCESS)(msg))

        # A dry run persists nothing, so there is no post-run state to verify. `None` keeps that
        # apart from an empty list, which would claim the check ran and found nothing.
        unclassified = None if dry_run else self._unclassified_cohort_ids(selection)

        # Log final summary
        change_pct = round((global_changed / global_total * 100), 2) if global_total > 0 else 0
        realtime_pct = round((global_prospective_realtime / global_total * 100), 2) if global_total > 0 else 0
        logger.info(
            "cohort_resave_completed",
            dry_run=dry_run,
            teams_processed=teams_processed,
            total_cohorts=global_total,
            changed_cohorts=global_changed,
            realtime_cohorts=global_prospective_realtime,
            error_count=global_errors,
            validation_error_count=global_validation_errors,
            stale_cache_team_count=len(stale_cache_team_ids),
            change_percentage=change_pct,
            realtime_percentage=realtime_pct,
            unclassified_count=None if unclassified is None else len(unclassified),
        )
        self.stdout.write("")
        healthy = global_errors == 0 and global_validation_errors == 0 and not stale_cache_team_ids and not unclassified
        final_style = self.style.SUCCESS if healthy else self.style.WARNING
        unclassified_label = "unclassified not checked" if unclassified is None else f"{len(unclassified)} unclassified"
        self.stdout.write(
            final_style(
                f"Done{dry_run_label}. "
                f"{teams_processed} teams, {global_total} cohorts, "
                f"{global_changed} changed ({change_pct}%), "
                f"{global_prospective_realtime} realtime ({realtime_pct}%), "
                f"{global_errors} errors, {global_validation_errors} validation errors, "
                f"{len(stale_cache_team_ids)} teams with a stale flags cache, "
                f"{unclassified_label}"
            )
        )

        if unclassified and selection.explicit:
            self._fail_on_unclassified(unclassified)

        if stale_cache_team_ids:
            self._fail_on_stale_cache(stale_cache_team_ids)

    def _unclassified_cohort_ids(self, selection: TeamSelection) -> list[int]:
        """Cohorts the realtime gate routes that still have a null `condition_type`, read back from
        the database.

        Reading persisted state covers every way a cohort ends up unclassified: a save that raised, a
        filter set the validator rejected, and a well-formed filter group with no leaf conditions,
        which the resave classifies as realtime and leaves with a null `condition_type`. It only
        means anything after a run that persisted, so the caller skips it on a dry run.
        """
        qs = Cohort.objects.filter(cohort_type__in=REALTIME_GATED_COHORT_TYPES, condition_type__isnull=True)
        if selection.team_ids is not None:
            qs = qs.filter(team_id__in=selection.team_ids)
        return list(qs.order_by("id").values_list("id", flat=True))

    def _fail_on_unclassified(self, cohort_ids: list[int]) -> None:
        """Refuse to report success while a gated cohort still has a null `condition_type`.

        The realtime membership gate reads a null `condition_type` as "no behavioral condition", so
        an unclassified cohort silently evaluates as if it had none.
        """
        raise UnclassifiedCohortsError(
            f"{len(cohort_ids)} cohorts still have a null condition_type: {_summarize_ids(cohort_ids)}. "
            "Fix their filters and rerun before treating the team as classified. "
            "Deleted cohorts count too, because restoring one returns it to the realtime gate unclassified."
        )

    def _fail_on_stale_cache(self, team_ids: list[int]) -> None:
        """Refuse to report success while a team still serves the cohort rules the run replaced.

        The rebuild never reached the broker, and nothing sweeps that back: the service-cache
        verifier does not compare cohorts, and a rerun finds nothing left to change.
        """
        raise StaleFlagsCacheError(
            f"{len(team_ids)} teams kept a stale flags cache: {_summarize_ids(team_ids)}. "
            "A rerun changes nothing, so enqueue update_team_flags_cache and "
            "update_team_service_flags_cache for them."
        )

    def _existing_team_ids(self, requested: list[int]) -> tuple[int, ...]:
        """Refuse team ids that do not exist, so a typo cannot pass as a clean run over no cohorts."""
        found = set(Team.objects.filter(id__in=requested).values_list("id", flat=True))
        missing = sorted({team_id for team_id in requested if team_id not in found})
        if missing:
            raise CommandError(f"No team with id {', '.join(str(team_id) for team_id in missing)}")
        return tuple(sorted(found))

    def _resolve_teams(self, options: dict[str, Any]) -> TeamSelection:
        """Resolve the team selector into explicit ids, or None for every team."""
        team_ids: list[int] | None = options.get("team_id")
        realtime_allowlist: bool = bool(options.get("realtime_allowlist"))

        if team_ids is not None and realtime_allowlist:
            raise CommandError("Pass only one of --team-id, --realtime-allowlist")

        if team_ids is not None:
            if any(team_id <= 0 for team_id in team_ids):
                raise CommandError("--team-id must be a positive integer")
            resolved = self._existing_team_ids(team_ids)
            label = f"team {resolved[0]}" if len(resolved) == 1 else f"{len(resolved)} teams"
            return TeamSelection(team_ids=resolved, label=label, explicit=True)

        if realtime_allowlist:
            if realtime_allowlist_matches_every_team():
                # Scanning every team to rediscover that the allowlist matches all of them would
                # build an `IN` clause holding every team id, parsed once per queryset.
                return TeamSelection(
                    team_ids=None,
                    label="all teams (realtime allowlist matches every team)",
                    explicit=True,
                )
            allowed = tuple(
                candidate
                for candidate in Team.objects.order_by("id").values_list("id", flat=True)
                if is_realtime_cohort_team(candidate)
            )
            # An allowlist that matches nothing would resave nothing and still report success, which
            # during a rollout reads the same as "every cohort is classified".
            if not allowed:
                raise CommandError("REALTIME_COHORT_TEAM_ALLOWLIST matches no teams")
            return TeamSelection(
                team_ids=allowed,
                label=f"{len(allowed)} realtime-allowlisted teams",
                explicit=True,
            )

        return TeamSelection(team_ids=None, label="all teams", explicit=False)

    def _process_team_cohorts(
        self, team: Team, batch_size: int, dry_run: bool, coalesce_rebuilds: bool
    ) -> CohortResaveStats:
        """Process all cohorts for a single team."""
        # Initialize stats for this team
        total = 0
        changed = 0
        errors = 0
        validation_errors = 0
        prospective_realtime = 0

        # Get all cohorts for this team using pagination
        # Both the validation call below and `RootTeamMixin.save()` read `cohort.team`, so
        # without `select_related` every cohort in the loop costs a team query.
        base_qs = Cohort.objects.filter(team=team).select_related("team").order_by("id")
        all_cohorts = []
        last_id = 0

        while True:
            batch = list(base_qs.filter(id__gt=last_id)[:batch_size])
            if not batch:
                break
            all_cohorts.extend(batch)
            last_id = batch[-1].id

        # Build dependency information for all cohorts
        seen_cohorts_cache = {c.id: c for c in all_cohorts}
        cohort_dependencies = {}  # cohort_id -> set of all cohort ids it depends on

        for cohort in all_cohorts:
            if not cohort.filters:
                continue
            # Get ALL dependencies recursively (A->B->C means A depends on both B and C)
            dependencies = get_all_cohort_dependencies(cohort, seen_cohorts_cache=seen_cohorts_cache)
            dependency_ids = {dep.id for dep in dependencies}
            cohort_dependencies[cohort.id] = dependency_ids

        # Sort cohorts topologically - dependencies first, then dependents
        sorted_cohort_ids = sort_cohorts_topologically({c.id for c in all_cohorts}, seen_cohorts_cache)

        # Process cohorts in dependency order. Each save fires two whole-team flags-cache
        # rebuilds, so the block coalesces them into one dispatch per team. Scoping it to one
        # team means that team reads a stale cache only while its own cohorts are being resaved,
        # rather than until the whole run finishes. Without the SIGTERM unwind nothing flushes
        # the block on shutdown, so an unprotected run keeps the per-save enqueues instead.
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
                    # Skip cohorts without filters (nothing to recompute)
                    if not cohort.filters:
                        continue

                    # Compute the new filters with inline bytecode and cohort_type
                    # Use defensive validation with detailed error reporting
                    clean_filters, computed_type, validation_error_list = validate_filters_and_compute_realtime_support(
                        cohort.filters,
                        cohort.team,
                        current_cohort_type=cohort.cohort_type,
                        cohort_count=cohort.count,
                    )

                    # If validation failed but we got the original filters back, log the issue and skip
                    if validation_error_list:
                        validation_errors += 1
                        logger.warning(
                            "cohort_validation_skipped",
                            cohort_id=cohort.id,
                            team_id=team.pk,
                            reason="Invalid filter structure - keeping original filters",
                        )
                        continue

                    # Check if any directly referenced cohorts have dependencies
                    if computed_type == "realtime" and cohort.filters:
                        direct_refs = self._get_direct_cohort_references(cohort.filters)
                        for ref_id in direct_refs:
                            ref_cohort = seen_cohorts_cache.get(ref_id)
                            if ref_cohort:
                                # Static cohorts cannot be realtime, so any cohort referencing them can't be realtime
                                if ref_cohort.is_static:
                                    computed_type = None
                                    break
                                # Cohorts without filters (empty cohorts) can be considered realtime-compatible
                                # since they match no one (always false)
                                if not ref_cohort.filters:
                                    continue
                                # If any directly referenced cohort has dependencies, this cannot be realtime
                                if ref_id in cohort_dependencies and len(cohort_dependencies[ref_id]) > 0:
                                    computed_type = None
                                    break
                                # Also check if the referenced cohort is not realtime
                                if ref_cohort.cohort_type != "realtime":
                                    computed_type = None
                                    break

                    computed_condition_type = Cohort.compute_condition_type(clean_filters)

                    # Decide if there is any change worth persisting/reporting
                    will_change = (
                        clean_filters != cohort.filters
                        or computed_type != cohort.cohort_type
                        or computed_condition_type != cohort.condition_type
                    )

                    # ALWAYS update in-memory for dependency checking
                    cohort.filters = clean_filters
                    cohort.cohort_type = computed_type
                    cohort.condition_type = computed_condition_type

                    # Track summary stats
                    if computed_type == "realtime":
                        prospective_realtime += 1
                    if dry_run:
                        if will_change:
                            changed += 1
                        continue

                    # Persist changes to database if needed
                    if will_change:
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

    def _get_direct_cohort_references(self, filters: dict[str, Any]) -> set[int]:
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
                                referenced_ids.update(self._get_direct_cohort_references({"properties": value}))

        return referenced_ids
