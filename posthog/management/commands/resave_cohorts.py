from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

import structlog

from posthog.api.cohort import validate_filters_and_compute_realtime_support
from posthog.dataclasses import frozen
from posthog.models.team.team import Team

from products.cohorts.backend.models.cohort import Cohort, CohortType
from products.cohorts.backend.models.util import get_all_cohort_dependencies, sort_cohorts_topologically
from products.cohorts.backend.realtime_teams import is_realtime_cohort_team, realtime_allowlist_matches_every_team

logger = structlog.get_logger(__name__)

# How many unclassified cohort ids to name in the failure output before summarizing the rest.
UNCLASSIFIED_REPORT_LIMIT = 20

# The cohort types the realtime membership gate routes, so a null condition_type changes how they
# evaluate. See `uses_realtime_membership` in rust/feature-flags/src/cohorts/cohort_models.rs.
REALTIME_GATED_COHORT_TYPES = (CohortType.REALTIME, CohortType.BEHAVIORAL)


class UnclassifiedCohortsError(CommandError):
    """The run finished and persisted its saves, but left cohorts the realtime gate misreads.

    Distinct from the other `CommandError`s the command raises, which all reject the invocation
    before any work happens, so a caller can tell a run that never started from one that did.
    """


@frozen
class CohortResaveStats:
    total: int
    changed: int
    errors: int
    validation_errors: int
    prospective_realtime: int


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
        teams_processed = 0
        total_teams = teams_qs.count()

        # Process each team separately
        for team in teams_qs:
            teams_processed += 1
            logger.info(
                "cohort_resave_team_started",
                team_id=team.id,
                team_progress=f"{teams_processed}/{total_teams}",
            )
            self.stdout.write(f"Processing team {team.id} ({teams_processed}/{total_teams})")

            stats = self._process_team_cohorts(team, batch_size, dry_run)

            # Accumulate stats
            global_total += stats.total
            global_changed += stats.changed
            global_errors += stats.errors
            global_validation_errors += stats.validation_errors
            global_prospective_realtime += stats.prospective_realtime

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
                    dry_run=dry_run,
                )
                msg = f"  Team {team.id}: {stats.total} cohorts, {stats.changed} changed, {stats.prospective_realtime} realtime"
                if stats.errors > 0:
                    msg += f", {stats.errors} errors"
                if stats.validation_errors > 0:
                    msg += f", {stats.validation_errors} validation errors"
                style = self.style.WARNING if (stats.errors > 0 or stats.validation_errors > 0) else self.style.SUCCESS
                self.stdout.write(style(msg))

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
            change_percentage=change_pct,
            realtime_percentage=realtime_pct,
            unclassified_count=None if unclassified is None else len(unclassified),
        )
        self.stdout.write("")
        healthy = global_errors == 0 and global_validation_errors == 0 and not unclassified
        final_style = self.style.SUCCESS if healthy else self.style.WARNING
        unclassified_label = "unclassified not checked" if unclassified is None else f"{len(unclassified)} unclassified"
        self.stdout.write(
            final_style(
                f"Done{dry_run_label}. "
                f"{teams_processed} teams, {global_total} cohorts, "
                f"{global_changed} changed ({change_pct}%), "
                f"{global_prospective_realtime} realtime ({realtime_pct}%), "
                f"{global_errors} errors, {global_validation_errors} validation errors, "
                f"{unclassified_label}"
            )
        )

        if unclassified and selection.explicit:
            self._fail_on_unclassified(unclassified)

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
        shown = ", ".join(str(cohort_id) for cohort_id in cohort_ids[:UNCLASSIFIED_REPORT_LIMIT])
        remainder = len(cohort_ids) - UNCLASSIFIED_REPORT_LIMIT
        if remainder > 0:
            shown += f", and {remainder} more"
        raise UnclassifiedCohortsError(
            f"{len(cohort_ids)} cohorts still have a null condition_type: {shown}. "
            "Fix their filters and rerun before treating the team as classified. "
            "Deleted cohorts count too, because restoring one returns it to the realtime gate unclassified."
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

    def _process_team_cohorts(self, team: Team, batch_size: int, dry_run: bool) -> CohortResaveStats:
        """Process all cohorts for a single team."""
        # Initialize stats for this team
        total = 0
        changed = 0
        errors = 0
        validation_errors = 0
        prospective_realtime = 0

        # Get all cohorts for this team using pagination
        base_qs = Cohort.objects.filter(team=team).order_by("id")
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

        # Process cohorts in dependency order
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
                    cohort.filters, cohort.team, current_cohort_type=cohort.cohort_type, cohort_count=cohort.count
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
