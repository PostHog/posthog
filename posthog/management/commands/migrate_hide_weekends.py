from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand
from django.db.models import Q, QuerySet

import structlog

from products.product_analytics.backend.models.insight import Insight

logger = structlog.get_logger(__name__)

WEEKDAYS = [1, 2, 3, 4, 5]
# hideWeekends only ever removed day buckets, so on these intervals it was a no-op
NOOP_INTERVALS = {"hour", "minute", "week", "month", "quarter", "year"}
# Windowed math keeps counting weekend events inside weekday buckets, so filtering
# events with daysOfWeek would change the numbers
WINDOWED_MATHS = {"weekly_active", "monthly_active"}


def plan_migration(source: dict[str, Any]) -> tuple[str, str]:
    """Classify a TrendsQuery source as migrate (results identical under daysOfWeek),
    strip (hideWeekends was a no-op), or skip (migrating would change results)."""
    if source.get("kind") != "TrendsQuery":
        return "skip", "not a trends query"

    interval = source.get("interval") or "day"
    if interval in NOOP_INTERVALS:
        return "strip", f"hideWeekends is a no-op on {interval} interval"

    trends_filter = source.get("trendsFilter") or {}
    if any((series or {}).get("math") in WINDOWED_MATHS for series in source.get("series") or []):
        return "skip", "windowed aggregation (WAU/MAU) counts weekend events"
    if trends_filter.get("display") == "ActionsLineGraphCumulative":
        return "skip", "cumulative totals include weekend events"
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

        if dry_run:
            self.stdout.write(self.style.WARNING("Dry run - no changes will be made"))

        queryset: QuerySet[Insight] = Insight.objects.filter(
            Q(query__trendsFilter__hideWeekends=True) | Q(query__source__trendsFilter__hideWeekends=True)
        )
        if team_id is not None:
            queryset = queryset.filter(team_id=team_id)

        counts = {"migrate": 0, "strip": 0, "skip": 0}
        batch: list[Insight] = []

        for insight in queryset.iterator(chunk_size=batch_size):
            query = insight.query or {}
            source = query.get("source") if query.get("kind") == "InsightVizNode" else query
            if not isinstance(source, dict):
                counts["skip"] += 1
                continue

            action, reason = plan_migration(source)
            counts[action] += 1
            if action == "skip":
                self.stdout.write(f"Skipping insight {insight.id} (team {insight.team_id}): {reason}")
                continue

            apply_migration(source, action)
            batch.append(insight)
            if len(batch) >= batch_size:
                self._flush(batch, dry_run)

        self._flush(batch, dry_run)
        self.stdout.write(
            self.style.SUCCESS(
                f"Done: {counts['migrate']} migrated to daysOfWeek, "
                f"{counts['strip']} stripped (no-op), {counts['skip']} skipped"
            )
        )

    def _flush(self, batch: list[Insight], dry_run: bool) -> None:
        if batch and not dry_run:
            Insight.objects_including_soft_deleted.bulk_update(batch, ["query"])
        batch.clear()
