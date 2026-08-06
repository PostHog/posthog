from typing import Literal, Optional

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q

import structlog

from posthog.schema import BaseMathType, ChartDisplayType, IntervalType

from products.product_analytics.backend.models.insight import Insight

logger = structlog.get_logger(__name__)

MigrationOutcome = Literal["switch", "remove", "keep"]

# Displays whose response has no per-day buckets, so hideWeekends never drops anything.
# Mirrors TrendsDisplay.is_total_value in posthog/hogql_queries/insights/trends/display.py.
TOTAL_VALUE_DISPLAYS: set[str] = {
    ChartDisplayType.BOLD_NUMBER,
    ChartDisplayType.ACTIONS_PIE,
    ChartDisplayType.ACTIONS_BAR_VALUE,
    ChartDisplayType.WORLD_MAP,
    ChartDisplayType.CALENDAR_HEATMAP,
    ChartDisplayType.ACTIONS_TABLE,
}

# Intervals the trends runner exempts from hideWeekends bucket dropping.
EXEMPT_INTERVALS: set[str] = {
    IntervalType.MINUTE,
    IntervalType.HOUR,
    IntervalType.WEEK,
    IntervalType.MONTH,
    IntervalType.QUARTER,
    IntervalType.YEAR,
}

WINDOWED_MATHS: set[str] = {BaseMathType.WEEKLY_ACTIVE, BaseMathType.MONTHLY_ACTIVE}

ISO_WEEKDAYS: list[int] = [1, 2, 3, 4, 5]


def trends_source(query: Optional[dict]) -> Optional[dict]:
    """The TrendsQuery node inside an insight's query, whether wrapped in InsightVizNode or bare."""
    if not isinstance(query, dict):
        return None
    source = query.get("source") if query.get("kind") == "InsightVizNode" else query
    if isinstance(source, dict) and source.get("kind") == "TrendsQuery":
        return source
    return None


def classify_hide_weekends(source: dict) -> MigrationOutcome:
    """What this migration can safely do to a TrendsQuery with hideWeekends on.

    Mirrors the hideWeekends handling in trends_query_runner.py: buckets are only dropped for
    day-interval time-series responses, and weekend events stay in the aggregation. A rewrite to
    dateRange.daysOfWeek instead filters weekend events out, so it is only result-identical when
    no displayed value aggregates across days (rolling math, cumulative display, smoothing).
    """
    interval = source.get("interval") or "day"
    trends_filter = source.get("trendsFilter") or {}
    display = trends_filter.get("display") or ChartDisplayType.ACTIONS_LINE_GRAPH
    if interval in EXEMPT_INTERVALS or display in TOTAL_VALUE_DISPLAYS:
        return "remove"
    if interval != IntervalType.DAY:
        # "second" is not on the runner's exemption list, so hideWeekends drops buckets there,
        # while daysOfWeek only drops buckets at day interval; a rewrite would not be identical
        return "keep"
    series = source.get("series") or []
    has_windowed_math = any(isinstance(s, dict) and s.get("math") in WINDOWED_MATHS for s in series)
    smoothing_intervals = trends_filter.get("smoothingIntervals") or 1
    days_of_week = (source.get("dateRange") or {}).get("daysOfWeek") or []
    if (
        has_windowed_math
        or display == ChartDisplayType.ACTIONS_LINE_GRAPH_CUMULATIVE
        or smoothing_intervals > 1
        or days_of_week
    ):
        return "keep"
    return "switch"


class Command(BaseCommand):
    help = (
        "Migrate trends insights off the deprecated trendsFilter.hideWeekends display option, "
        "onto the dateRange.daysOfWeek filter where results are provably identical"
    )

    def add_arguments(self, parser):
        parser.add_argument("--batch-size", type=int, default=100, help="Number of insights to process per batch")
        parser.add_argument("--team-id", type=int, help="Process insights for a specific team only")
        parser.add_argument("--dry-run", action="store_true", help="Classify and report without writing any changes")

    def handle(self, *args, **options):
        batch_size: int = options["batch_size"]
        team_id: Optional[int] = options["team_id"]
        dry_run: bool = options["dry_run"]

        if dry_run:
            self.stdout.write(self.style.WARNING("Dry run: no changes will be made"))

        base_query = Insight.objects.filter(deleted=False).filter(
            Q(query__source__trendsFilter__hideWeekends=True) | Q(query__trendsFilter__hideWeekends=True)
        )
        if team_id:
            base_query = base_query.filter(team_id=team_id)

        insight_ids = list(base_query.order_by("id").values_list("id", flat=True))
        self.stdout.write(f"Found {len(insight_ids)} insights with hideWeekends enabled")

        counts: dict[str, int] = {"switch": 0, "remove": 0, "keep": 0, "skipped": 0}
        kept: list[str] = []

        for start in range(0, len(insight_ids), batch_size):
            chunk = insight_ids[start : start + batch_size]
            with transaction.atomic():
                insights = list(
                    Insight.objects.filter(id__in=chunk)
                    .select_for_update(skip_locked=True, of=("self",))
                    .only("id", "short_id", "team", "query", "deleted")
                )
                to_update = []
                for insight in insights:
                    source = trends_source(insight.query)
                    if not source or not (source.get("trendsFilter") or {}).get("hideWeekends"):
                        # Edited between the id scan and this lock; nothing left to migrate
                        counts["skipped"] += 1
                        continue
                    outcome = classify_hide_weekends(source)
                    counts[outcome] += 1
                    if outcome == "keep":
                        kept.append(insight.short_id)
                        continue
                    source["trendsFilter"].pop("hideWeekends", None)
                    if outcome == "switch":
                        source.setdefault("dateRange", {})["daysOfWeek"] = ISO_WEEKDAYS
                    to_update.append(insight)
                    logger.info(
                        "migrate_hide_weekends",
                        insight_id=insight.id,
                        short_id=insight.short_id,
                        team_id=insight.team_id,
                        outcome=outcome,
                        dry_run=dry_run,
                    )
                if to_update and not dry_run:
                    # bulk_update issues a plain UPDATE: last_modified_at and activity log stay
                    # untouched, so the change is invisible outside the query definition itself
                    Insight.objects.bulk_update(to_update, ["query"])
            self.stdout.write(f"Processed {start + len(chunk)}/{len(insight_ids)}")

        verb = "Would switch" if dry_run else "Switched"
        self.stdout.write(
            self.style.SUCCESS(
                f"{verb} {counts['switch']} insights to daysOfWeek and removed the no-op flag from {counts['remove']}"
            )
        )
        self.stdout.write(f"Kept (results would change): {counts['keep']}")
        if kept:
            self.stdout.write(f"Kept short_ids: {', '.join(kept)}")
        if counts["skipped"]:
            self.stdout.write(f"Skipped (changed concurrently): {counts['skipped']}")
