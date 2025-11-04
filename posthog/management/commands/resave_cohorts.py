from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from posthog.api.cohort import validate_filters_and_compute_realtime_support
from posthog.models.cohort.cohort import Cohort
from posthog.models.cohort.util import get_all_cohort_dependencies, sort_cohorts_topologically
from posthog.models.team.team import Team


class Command(BaseCommand):
    help = "Regenerate inline bytecode (in filters) and cohort_type for cohorts."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--team-id",
            type=int,
            help="Team ID to process; if omitted, processes all teams.",
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
        team_id = options.get("team_id")
        dry_run: bool = bool(options.get("dry_run"))
        batch_size: int = int(options.get("batch_size") or 500)

        # Announce run scope and options for operator visibility
        scope_desc = f"team={team_id}" if team_id else "all teams"
        self.stdout.write(
            self.style.MIGRATE_HEADING(
                f"Starting cohort resave ({scope_desc}, dry_run={dry_run}, batch_size={batch_size})"
            )
        )

        # Get teams to process
        teams_qs = Team.objects.all().order_by("id")
        if team_id:
            teams_qs = teams_qs.filter(id=team_id)

        # Track global stats
        global_total = 0
        global_changed = 0
        global_errors = 0
        global_prospective_realtime = 0
        teams_processed = 0
        total_teams = teams_qs.count()

        # Process each team separately
        for team in teams_qs:
            teams_processed += 1
            self.stdout.write(self.style.MIGRATE_LABEL(f"Processing team {team.id} ({teams_processed}/{total_teams})"))

            stats = self._process_team_cohorts(team, batch_size, dry_run)

            # Accumulate stats
            global_total += stats["total"]
            global_changed += stats["changed"]
            global_errors += stats["errors"]
            global_prospective_realtime += stats["prospective_realtime"]

            # Report team stats
            if stats["total"] > 0:
                self.stdout.write(
                    f"  Team {team.id}: processed={stats['total']} changed={stats['changed']} "
                    f"realtime={stats['prospective_realtime']} errors={stats['errors']}"
                )

        # Final summary
        if dry_run:
            self.stdout.write(
                self.style.SUCCESS(
                    f"\nDone (dry-run). teams={teams_processed} total_cohorts={global_total} "
                    f"would_change={global_changed} would_be_realtime={global_prospective_realtime} "
                    f"errors={global_errors}"
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"\nDone. teams={teams_processed} total_cohorts={global_total} "
                    f"changed={global_changed} realtime_now={global_prospective_realtime} "
                    f"errors={global_errors}"
                )
            )

    def _process_team_cohorts(self, team: Team, batch_size: int, dry_run: bool) -> dict[str, int]:
        """Process all cohorts for a single team."""
        # Initialize stats for this team
        total = 0
        changed = 0
        errors = 0
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
                clean_filters, computed_type, _ = validate_filters_and_compute_realtime_support(
                    cohort.filters, cohort.team, current_cohort_type=cohort.cohort_type
                )

                # Check if any directly referenced cohorts have dependencies
                if computed_type == "realtime" and cohort.filters:
                    direct_refs = self._get_direct_cohort_references(cohort.filters)
                    for ref_id in direct_refs:
                        # If any directly referenced cohort has dependencies, this cannot be realtime
                        if ref_id in cohort_dependencies and len(cohort_dependencies[ref_id]) > 0:
                            computed_type = None
                            break
                        # Also check if the referenced cohort is not realtime
                        ref_cohort = seen_cohorts_cache.get(ref_id)
                        if ref_cohort and ref_cohort.cohort_type != "realtime":
                            computed_type = None
                            break

                # Decide if there is any change worth persisting/reporting
                will_change = clean_filters != cohort.filters or computed_type != cohort.cohort_type

                # ALWAYS update in-memory for dependency checking
                cohort.filters = clean_filters
                cohort.cohort_type = computed_type

                # Track summary stats
                if computed_type == "realtime":
                    prospective_realtime += 1
                if dry_run:
                    if will_change:
                        changed += 1
                    continue

                # Persist changes to database if needed
                if will_change:
                    cohort.save(update_fields=["filters", "cohort_type"])
                    changed += 1
            except Exception as err:
                errors += 1
                self.stderr.write(self.style.ERROR(f"Cohort {cohort.id} (team {team.id}): {err}"))

        return {
            "total": total,
            "changed": changed,
            "errors": errors,
            "prospective_realtime": prospective_realtime,
        }

    def _get_direct_cohort_references(self, filters: dict[str, Any]) -> set[int]:
        """Get only the direct cohort references from filters (not transitive)."""
        referenced_ids = set()
        if not isinstance(filters, dict):
            return referenced_ids

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
