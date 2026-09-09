"""Clear breakdown color entries a dashboard cannot apply.

`Dashboard.breakdown_colors` holds a list of entries, each pinning one breakdown value to one
palette slot. No write path checked that for months, so callers stored an object keyed by breakdown
value, an empty object, a JSON-encoded string, lists of bare values, entries under other key names
such as `breakdown_value` and `color`, and entries whose token is a CSS color. Two of those shapes
give every viewer an error screen instead of tiles on every load. The rest never render, so the
colors silently do nothing.

Dropped entries are not recoverable from what stays. A run reports ids and counts only, because a
breakdown value is customer data and a command runner can retain what a command prints. To keep a
record of what a live run would drop, take a dry run with `--show-values` somewhere the output is
not retained. Re-running is safe: a row already cleared reports no change.

Usage:
    # Dry-run (the default): reports what it would change and writes nothing
    python manage.py clear_unusable_breakdown_colors

    # Live run
    python manage.py clear_unusable_breakdown_colors --live-run

    # Restrict to one team or one dashboard
    python manage.py clear_unusable_breakdown_colors --live-run --team-id 2
    python manage.py clear_unusable_breakdown_colors --live-run --dashboard-id 1234

    # Print the stored and cleared values as well
    python manage.py clear_unusable_breakdown_colors --show-values
"""

from __future__ import annotations

import re
import time
from collections import Counter
from collections.abc import Iterator
from typing import Any, Literal

from django.core.management.base import BaseCommand
from django.db.models import QuerySet

import structlog

from posthog.dataclasses import frozen

from products.dashboards.backend.models.dashboard import Dashboard

logger = structlog.get_logger(__name__)

# A token names a slot in the dashboard's color theme, not a color. `getColorFromToken` parses the N
# out of `preset-N` and indexes the theme with it, so a hex value there yields `theme['preset-NaN']`,
# which is undefined. A pattern rather than a fixed range, because a theme can carry more slots than
# the default palette and the token wraps past its end.
#
# Kept identical to the `colorToken` pattern the API validates writes against, in
# products/dashboards/backend/widget_specs/openapi.py. A token this keeps but the API rejects would
# leave the dashboard's next save failing with a 400 its owner cannot act on.
_COLOR_TOKEN = re.compile(r"^preset-[1-9][0-9]*$")

Outcome = Literal["written", "dry_run", "concurrent_save"]


@frozen
class BreakdownColorsChange:
    dashboard_id: int
    team_id: int
    stored: Any
    cleared: Any
    outcome: Outcome

    @property
    def summary(self) -> str:
        if isinstance(self.stored, list):
            return f"dropped {len(self.stored) - len(self.cleared)} of {len(self.stored)} entries"
        return f"replaced a stored {type(self.stored).__name__} with an empty list"


def _can_apply(entry: Any) -> bool:
    if not isinstance(entry, dict) or "breakdownValue" not in entry or "colorToken" not in entry:
        return False
    token = entry["colorToken"]
    # A null token is the shape of a color a person cleared, which the frontend reads as no color
    # rather than as a broken one.
    if token is None:
        return True
    return isinstance(token, str) and _COLOR_TOKEN.match(token) is not None


def clear_unusable_entries(stored: Any) -> Any:
    # A null column means the dashboard never had colors, so there is nothing to clear. Django reads
    # a stored JSON null as None as well, and the API returns both as null.
    if stored is None:
        return None
    # A value that is not a list cannot hold entries at all, so no entry survives it.
    if not isinstance(stored, list):
        return []
    # Each surviving entry is kept as stored, so a key this command does not know about survives and
    # a color saved by a later frontend is not lost. Entries also keep their stored order, because a
    # dashboard save diffs the color list against what is persisted, and a reordered list would show
    # as an unsaved change on a dashboard this otherwise leaves alone.
    return [entry for entry in stored if _can_apply(entry)]


def _candidates(team_id: int | None, dashboard_id: int | None) -> QuerySet[Dashboard]:
    # A soft-deleted dashboard can be restored, so it needs the fix too.
    dashboards = Dashboard.objects_including_soft_deleted.filter(breakdown_colors__isnull=False).exclude(
        breakdown_colors=[]
    )
    if team_id is not None:
        dashboards = dashboards.filter(team_id=team_id)
    if dashboard_id is not None:
        dashboards = dashboards.filter(id=dashboard_id)
    return dashboards.order_by("id")


def _write(dashboard_id: int, team_id: int, stored: Any, cleared: Any, live_run: bool) -> BreakdownColorsChange:
    outcome: Outcome = "dry_run"
    if live_run:
        # The value read is part of the filter, so the update lands only while the row still holds
        # it. A save that arrives between the read and the write leaves the row unmatched and keeps
        # its own value, instead of losing it to a value read before it.
        updated = Dashboard.objects_including_soft_deleted.filter(id=dashboard_id, breakdown_colors=stored).update(
            breakdown_colors=cleared
        )
        outcome = "written" if updated else "concurrent_save"
    return BreakdownColorsChange(
        dashboard_id=dashboard_id, team_id=team_id, stored=stored, cleared=cleared, outcome=outcome
    )


def clear_unusable_breakdown_colors(
    *,
    live_run: bool,
    team_id: int | None = None,
    dashboard_id: int | None = None,
    batch_size: int = 1000,
    sleep_interval: float = 0.0,
) -> Iterator[BreakdownColorsChange]:
    candidates = _candidates(team_id, dashboard_id)
    after_id = 0
    while True:
        batch = list(candidates.filter(id__gt=after_id).values_list("id", "team_id", "breakdown_colors")[:batch_size])
        if not batch:
            return
        after_id = batch[-1][0]
        for row_id, row_team_id, stored in batch:
            cleared = clear_unusable_entries(stored)
            if cleared == stored:
                continue
            yield _write(row_id, row_team_id, stored, cleared, live_run)
        if sleep_interval > 0:
            time.sleep(sleep_interval)


class Command(BaseCommand):
    help = "Clear breakdown color entries a dashboard cannot apply, keeping the rest in their stored order."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--live-run", action="store_true", help="Apply changes (default is dry-run).")
        parser.add_argument("--team-id", type=int, default=None, help="Restrict to dashboards of this team.")
        parser.add_argument("--dashboard-id", type=int, default=None, help="Restrict to a single dashboard.")
        parser.add_argument("--batch-size", type=int, default=1000, help="Dashboards read per query (default: 1000).")
        parser.add_argument(
            "--sleep-interval", type=float, default=0.2, help="Seconds to wait between batches (default: 0.2)."
        )
        parser.add_argument(
            "--show-values",
            action="store_true",
            help=(
                "Also print the stored and cleared values. A breakdown value is customer data, so "
                "only use this where the output is not retained."
            ),
        )

    def handle(self, *args: Any, **options: Any) -> None:
        live_run: bool = options["live_run"]
        show_values: bool = options["show_values"]
        counts: Counter[Outcome] = Counter()
        prefix = "[live] " if live_run else "[dry-run] "

        for change in clear_unusable_breakdown_colors(
            live_run=live_run,
            team_id=options["team_id"],
            dashboard_id=options["dashboard_id"],
            batch_size=options["batch_size"],
            sleep_interval=options["sleep_interval"],
        ):
            counts[change.outcome] += 1
            # The values stay behind a flag because a breakdown value is customer data and a command
            # runner can retain what a command prints. Ids and counts are enough to follow a run.
            line = f"{prefix}dashboard {change.dashboard_id} (team={change.team_id}) {change.outcome}: {change.summary}"
            if show_values:
                line += f" | {change.stored!r} -> {change.cleared!r}"
            self.stdout.write(line)

        logger.info(
            "Cleared unusable breakdown colors",
            live_run=live_run,
            written=counts["written"],
            would_change=counts["dry_run"],
            skipped_concurrent_save=counts["concurrent_save"],
        )
        self.stdout.write(
            f"Done (live_run={live_run}). written={counts['written']} would_change={counts['dry_run']} "
            f"skipped_concurrent_save={counts['concurrent_save']}"
        )
