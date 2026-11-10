from __future__ import annotations

from contextlib import AbstractContextManager, nullcontext
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

import structlog

from posthog.cohort_resave import resave_team_cohorts, termination_unwinds, unclassified_cohort_ids
from posthog.dataclasses import frozen
from posthog.models.team.team import Team

from products.cohorts.backend.realtime_teams import (
    backfill_triggers_suppressed,
    is_processing_team,
    realtime_allowlist_matches_every_team,
)

logger = structlog.get_logger(__name__)

# How many ids to name in a failure message before summarizing the rest.
ID_REPORT_LIMIT = 20


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
            help="Process the teams the realtime pipeline processes: REALTIME_COHORT_TEAM_ALLOWLIST plus granted teams.",
        )
        parser.add_argument(
            "--no-backfill-triggers",
            action="store_true",
            help="Enqueue no backfill run for a resaved cohort, whatever the team's trigger settings say.",
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
        backfill_triggers: AbstractContextManager[None] = (
            backfill_triggers_suppressed() if options.get("no_backfill_triggers") else nullcontext()
        )

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
        with termination_unwinds() as coalesce_rebuilds, backfill_triggers:
            for team in teams_qs:
                teams_processed += 1
                logger.info(
                    "cohort_resave_team_started",
                    team_id=team.id,
                    team_progress=f"{teams_processed}/{total_teams}",
                )
                self.stdout.write(f"Processing team {team.id} ({teams_processed}/{total_teams})")

                stats = resave_team_cohorts(
                    team, batch_size=batch_size, dry_run=dry_run, coalesce_rebuilds=coalesce_rebuilds
                )

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
        unclassified = None if dry_run else unclassified_cohort_ids(selection.team_ids)

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
                if is_processing_team(candidate)
            )
            # An allowlist that matches nothing would resave nothing and still report success, which
            # during a rollout reads the same as "every cohort is classified".
            if not allowed:
                raise CommandError("--realtime-allowlist matches no teams")
            return TeamSelection(
                team_ids=allowed,
                label=f"{len(allowed)} realtime-processed teams",
                explicit=True,
            )

        return TeamSelection(team_ids=None, label="all teams", explicit=False)
