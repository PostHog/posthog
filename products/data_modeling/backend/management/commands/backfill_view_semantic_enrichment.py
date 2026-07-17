import time
from collections import Counter
from typing import Any

from django.core.management.base import BaseCommand, CommandError

import structlog

from products.data_modeling.backend.logic.enrich_view_semantics import (
    dispatch_view_enrichment,
    enrichment_gates_pass,
    view_ready_for_enrichment,
)
from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery

logger = structlog.get_logger(__name__)

DEFAULT_SLEEP_SECONDS = 0.2


class Command(BaseCommand):
    help = (
        "Backfill AI semantic descriptions for existing data-modeling views by dispatching the same "
        "enrichment workflow the save signal uses. Views only re-enrich on save/materialization, so views "
        "that predate the feature never get descriptions. Dry-run by default; pass --live-run to dispatch."
    )

    def add_arguments(self, parser: Any) -> None:
        target = parser.add_mutually_exclusive_group(required=True)
        target.add_argument(
            "--team-ids",
            type=int,
            nargs="+",
            help="Only backfill views for these team IDs (space-separated).",
        )
        target.add_argument(
            "--all",
            action="store_true",
            help="Backfill views across every team. Use with --limit / --sleep to avoid overload.",
        )
        parser.add_argument(
            "--live-run",
            action="store_true",
            help="Actually dispatch enrichment workflows. Without it, the command only reports what it would do.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Stop after dispatching this many workflows (safety cap for fleet-wide runs).",
        )
        parser.add_argument(
            "--sleep",
            type=float,
            default=DEFAULT_SLEEP_SECONDS,
            help=f"Seconds to sleep after each dispatch to spread queue load (default {DEFAULT_SLEEP_SECONDS}).",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        team_ids: list[int] | None = options["team_ids"]
        live_run: bool = options["live_run"]
        limit: int | None = options["limit"]
        sleep_seconds: float = options["sleep"]

        if limit is not None and limit <= 0:
            raise CommandError("--limit must be a positive integer")

        queryset = (
            DataWarehouseSavedQuery.objects.filter(deleted=False, is_test=False, managed_viewset__isnull=True)
            .select_related("team", "team__organization")
            .order_by("team_id", "id")
        )
        if team_ids:
            queryset = queryset.filter(team_id__in=team_ids)

        # Flag + AI-consent are per team, not per view, so evaluate the team gate once and reuse it for
        # every view that team owns (the queryset is ordered by team_id).
        team_gate: dict[int, bool] = {}
        per_team_dispatched: Counter[int] = Counter()
        scanned = 0
        dispatched = 0
        truncated = False

        for saved_query in queryset.iterator(chunk_size=500):
            if limit is not None and dispatched >= limit:
                truncated = True
                break

            scanned += 1
            team_id = saved_query.team_id
            if team_id not in team_gate:
                team_gate[team_id] = enrichment_gates_pass(saved_query)
            if not team_gate[team_id]:
                continue
            if not view_ready_for_enrichment(saved_query):
                continue

            if live_run:
                dispatch_view_enrichment(team_id, str(saved_query.id))
                if sleep_seconds > 0:
                    time.sleep(sleep_seconds)

            dispatched += 1
            per_team_dispatched[team_id] += 1

        self._report(
            live_run=live_run,
            scanned=scanned,
            dispatched=dispatched,
            per_team_dispatched=per_team_dispatched,
            truncated=truncated,
            limit=limit,
        )

    def _report(
        self,
        *,
        live_run: bool,
        scanned: int,
        dispatched: int,
        per_team_dispatched: "Counter[int]",
        truncated: bool,
        limit: int | None,
    ) -> None:
        verb = "dispatched" if live_run else "would dispatch"
        logger.info(
            "view_enrichment_backfill.done",
            live_run=live_run,
            scanned=scanned,
            dispatched=dispatched,
            teams=len(per_team_dispatched),
            truncated=truncated,
        )
        self.stdout.write(f"Scanned {scanned} view(s); {verb} {dispatched} across {len(per_team_dispatched)} team(s).")
        for team_id, count in sorted(per_team_dispatched.items()):
            self.stdout.write(f"  team {team_id}: {count}")
        if not live_run:
            self.stdout.write("Dry run: nothing was dispatched. Re-run with --live-run to enqueue workflows.")
        if truncated:
            self.stdout.write(
                self.style.WARNING(
                    f"Stopped at --limit {limit}; more views remain. Re-run to continue (already-enriched "
                    "views are skipped)."
                )
            )
