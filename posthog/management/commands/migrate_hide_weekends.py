from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q, QuerySet

import structlog

from products.product_analytics.backend.models.insight import Insight

logger = structlog.get_logger(__name__)

WEEKDAYS = [1, 2, 3, 4, 5]
# hideWeekends only ever removed day buckets, so on these intervals it was a no-op
NOOP_INTERVALS = {"hour", "minute", "week", "month", "quarter", "year"}
# These displays render aggregated_value from a query with no day_start, so hideWeekends
# (a day-bucket filter) was always a no-op on them; matches TrendsDisplay.is_total_value()
TOTAL_VALUE_DISPLAYS = {"BoldNumber", "ActionsPie", "ActionsBarValue", "ActionsTable", "WorldMap", "CalendarHeatmap"}
# These maths keep counting weekend events inside weekday buckets (WAU/MAU windows, and
# first_matching_event_for_user's conditional aggregation), so filtering events with
# daysOfWeek would change the numbers
RESULT_CHANGING_MATHS = {"weekly_active", "monthly_active", "first_matching_event_for_user"}


def source_of(query: dict[str, Any] | None) -> dict[str, Any] | None:
    """The query body, unwrapping the InsightVizNode envelope when there is one."""
    query = query or {}
    source = query.get("source") if query.get("kind") == "InsightVizNode" else query
    return source if isinstance(source, dict) else None


def plan_migration(source: dict[str, Any]) -> tuple[str, str]:
    """Classify a TrendsQuery source as migrate (results identical under daysOfWeek),
    strip (hideWeekends was a no-op), or skip (migrating would change results)."""
    if source.get("kind") != "TrendsQuery":
        return "skip", "not a trends query"

    interval = source.get("interval") or "day"
    if interval in NOOP_INTERVALS:
        return "strip", f"hideWeekends is a no-op on {interval} interval"

    trends_filter = source.get("trendsFilter") or {}
    if any((series or {}).get("math") in RESULT_CHANGING_MATHS for series in source.get("series") or []):
        return "skip", "windowed or conditional aggregation counts weekend events"
    display = trends_filter.get("display")
    if display == "ActionsLineGraphCumulative":
        return "skip", "cumulative totals include weekend events"
    if display in TOTAL_VALUE_DISPLAYS:
        return "strip", f"hideWeekends is a no-op on the {display} display"
    if (trends_filter.get("smoothingIntervals") or 1) > 1:
        return "skip", "daysOfWeek is not supported together with smoothing"

    existing_days = (source.get("dateRange") or {}).get("daysOfWeek")
    if existing_days and not any(day in WEEKDAYS for day in existing_days):
        return "skip", "existing daysOfWeek has no weekday overlap"

    return "migrate", ""


def apply_migration(source: dict[str, Any], action: str) -> None:
    trends_filter = source.get("trendsFilter")
    if isinstance(trends_filter, dict):
        trends_filter.pop("hideWeekends", None)
    if action == "migrate":
        date_range = source.get("dateRange") or {}
        existing_days = date_range.get("daysOfWeek")
        date_range["daysOfWeek"] = [day for day in existing_days if day in WEEKDAYS] if existing_days else WEEKDAYS
        source["dateRange"] = date_range


class Command(BaseCommand):
    help = (
        "Migrate insights from the deprecated display-only trendsFilter.hideWeekends "
        "to the query-level dateRange.daysOfWeek filter, where results are provably identical"
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--batch-size", type=int, default=100, help="Number of insights to update per batch")
        parser.add_argument("--team-id", type=int, help="Process insights for a specific team only")
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would change without writing to the database",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        batch_size: int = options["batch_size"]
        team_id: int | None = options["team_id"]
        dry_run: bool = options["dry_run"]

        if batch_size <= 0:
            raise CommandError(f"--batch-size must be a positive integer, got {batch_size}")

        if dry_run:
            self.stdout.write(self.style.WARNING("Dry run - no changes will be made"))

        queryset: QuerySet[Insight] = Insight.objects.filter(
            Q(query__trendsFilter__hideWeekends=True) | Q(query__source__trendsFilter__hideWeekends=True)
        )
        if team_id is not None:
            queryset = queryset.filter(team_id=team_id)

        counts = {"migrate": 0, "strip": 0, "skip": 0}
        batch: list[int] = []

        for insight in queryset.iterator(chunk_size=batch_size):
            source = source_of(insight.query)
            if source is None:
                counts["skip"] += 1
                continue

            action, reason = plan_migration(source)
            counts[action] += 1
            if action == "skip":
                self.stdout.write(f"Skipping insight {insight.id} (team {insight.team_id}): {reason}")
                continue

            batch.append(insight.id)
            if len(batch) >= batch_size:
                self._flush(batch, dry_run)

        self._flush(batch, dry_run)
        self.stdout.write(
            self.style.SUCCESS(
                f"Done: {counts['migrate']} migrated to daysOfWeek, "
                f"{counts['strip']} stripped (no-op), {counts['skip']} skipped"
            )
        )

    def _flush(self, insight_ids: list[int], dry_run: bool) -> None:
        # `query` is written as a whole column, so re-read and re-plan each row under a lock
        # rather than writing back the snapshot taken during the scan — otherwise an edit the
        # user made to the same insight in between is silently overwritten.
        if insight_ids and not dry_run:
            with transaction.atomic():
                for insight in Insight.objects.select_for_update().filter(id__in=insight_ids):
                    source = source_of(insight.query)
                    if source is None:
                        continue
                    action, _ = plan_migration(source)
                    if action == "skip":
                        continue
                    apply_migration(source, action)
                    insight.save(update_fields=["query"])
        insight_ids.clear()
