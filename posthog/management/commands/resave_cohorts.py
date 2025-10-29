from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from posthog.api.cohort import extract_bytecode_from_filters
from posthog.models.cohort.cohort import Cohort


class Command(BaseCommand):
    help = (
        "Regenerate compiled_bytecode and cohort_type for cohorts. "
        "If --team-id is provided, only that team's cohorts are processed; otherwise all cohorts are processed. "
        "Always processes in paginated batches to avoid large memory usage."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        # Scope selection: either target a single team or all cohorts
        parser.add_argument(
            "--team-id",
            type=int,
            default=None,
            help="Optional team id to process. If omitted, all teams are processed.",
        )
        # Performance guardrail: process in small batches to avoid memory pressure
        parser.add_argument(
            "--batch-size",
            type=int,
            default=500,
            help="Number of cohorts to process per batch (default: 500)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="If set, do not persist any changes; only report what would change.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        # Parse CLI arguments
        team_id = options.get("team_id")
        dry_run: bool = bool(options.get("dry_run"))
        batch_size: int = int(options.get("batch_size") or 500)

        # Establish base queryset and ordering for deterministic keyset pagination
        base_qs = Cohort.objects.all().order_by("id")
        if team_id:
            base_qs = base_qs.filter(team__id=team_id)

        total = 0
        changed = 0
        errors = 0
        prospective_realtime = 0  # how many would be realtime after processing

        # Announce run scope and options for operator visibility
        scope_desc = f"team={team_id}" if team_id else "all teams"
        self.stdout.write(
            self.style.MIGRATE_HEADING(
                f"Starting cohort resave ({scope_desc}, dry_run={dry_run}, batch_size={batch_size})"
            )
        )

        # Keyset pagination: iterate by increasing id, limited by batch_size
        last_id = 0
        while True:
            batch = list(base_qs.filter(id__gt=last_id)[:batch_size])
            if not batch:
                break
            for cohort in batch:
                total += 1
                try:
                    # Skip cohorts without filters (nothing to recompute)
                    if not cohort.filters:
                        continue

                    # Compute the new clean filters, type and bytecode from current filters
                    clean_filters, computed_type, compiled_bytecode = extract_bytecode_from_filters(
                        cohort.filters, cohort.team, current_cohort_type=cohort.cohort_type
                    )

                    # Decide if there is any change worth persisting/reporting
                    will_change = (
                        clean_filters != cohort.filters
                        or computed_type != cohort.cohort_type
                        or (compiled_bytecode or None) != (cohort.compiled_bytecode or None)
                    )

                    # Track summary stats for dry-run (no per-cohort logging)
                    if computed_type == "realtime":
                        prospective_realtime += 1
                    if dry_run:
                        if will_change:
                            changed += 1
                        continue

                    # Persist changes without triggering recalculation jobs
                    if will_change:
                        cohort.filters = clean_filters
                        cohort.cohort_type = computed_type
                        cohort.compiled_bytecode = compiled_bytecode
                        cohort.save(update_fields=["filters", "cohort_type", "compiled_bytecode"])  # no enqueue
                        changed += 1
                except Exception as err:
                    errors += 1
                    self.stderr.write(self.style.ERROR(f"Cohort {getattr(cohort, 'id', '?')}: {err}"))

            # Advance the keyset cursor
            last_id = batch[-1].id

        if dry_run:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Done (dry-run). total={total} would_change={changed} would_be_realtime={prospective_realtime} errors={errors}"
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Done. total={total} changed={changed} realtime_now={prospective_realtime} errors={errors}"
                )
            )

    # Keeping a stub to avoid accidental import errors if referenced elsewhere in future
    def _parse_team_ids(self, *_args: Any, **_kwargs: Any) -> list[int] | None:
        return None
