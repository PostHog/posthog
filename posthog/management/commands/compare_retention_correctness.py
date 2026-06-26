"""Fast correctness-only check: legacy vs new ("DWH variant") retention base query.

A stripped-down companion to ``compare_retention_legacy_vs_dwh``: no timing, no query-log
resource stats, no HogQL embedding, no per-insight report blocks. It runs each affected
RetentionQuery insight twice (variant OFF then ON), diffs the two result sets, and prints a
one-line-per-mismatch summary. The expensive parts of the full tool are gone and insights are
checked concurrently, so a correctness sweep finishes in a fraction of the time.

Concurrency is spread *across teams*, never within one. The unit of parallelism is a team: each
team's insights are checked serially in a single lane, and up to ``--concurrency`` distinct teams
run at once. This means two concurrent queries always hit different teams' data — different
primary-key ranges in ClickHouse — rather than hammering the same team's event granules twice over.
A consequence worth knowing: if the selected set is dominated by one team, effective parallelism
drops toward serial, which is the intended safety behaviour.

Correctness semantics are *identical* to the full tool — it imports and reuses the same
``classify_insight`` / ``diff_retention_results`` / ``compute_interval_context`` helpers, including
the trailing-period exclusion that keeps live-ingest drift on the in-progress interval from showing
up as a false mismatch. Strictly read-only.

The variant toggle is process-global, so instead of nesting a ``patch`` per call (which would race
across worker threads) we install one process-wide patch whose return value is read from a
``ContextVar`` each worker sets before it runs. Threads start with a fresh context, so the workers
never collide.

Examples:
    # All retention insights, up to 8 teams in parallel
    python manage.py compare_retention_correctness

    # One team, serial (e.g. to avoid extra ClickHouse load on prod)
    python manage.py compare_retention_correctness --team-id 42 --concurrency 1

    # CI gate: non-zero exit if anything mismatches
    python manage.py compare_retention_correctness --fail-on-mismatch
"""

import sys
import argparse
import threading
import contextvars
import dataclasses
from collections import defaultdict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from typing import Any, Optional

from unittest.mock import patch

from django.core.management.base import BaseCommand, CommandError
from django.db import connections

from posthog.schema import HogQLQueryModifiers

from posthog.hogql.modifiers import create_default_modifiers_for_team

from posthog.hogql_queries.insights.retention.test.retention_base_query_variant import (
    RETENTION_BASE_QUERY_VARIANT_PATCH_PATH,
)
from posthog.hogql_queries.query_runner import get_query_runner
from posthog.management.commands.compare_retention_legacy_vs_dwh import (
    classify_insight,
    compute_interval_context,
    diff_retention_results,
)

from products.product_analytics.backend.models.insight import Insight

# Per-thread variant selector. The single process-wide patch below reads this, so concurrent
# workers each pick their own variant without stepping on a shared global.
_use_dwh_var: contextvars.ContextVar[bool] = contextvars.ContextVar("retention_use_dwh", default=False)


@dataclasses.dataclass
class Row:
    short_id: str
    team_id: int
    url: str
    status: str  # "OK" | "MISMATCH" | "ERROR" | "SKIPPED"
    detail: str = ""


def _run_variant(
    insight: Insight, use_dwh: bool, modifiers: HogQLQueryModifiers, override: Optional[dict[str, Any]]
) -> list:
    source = deepcopy(insight.query["source"])
    if override is not None:
        source["dateRange"] = override
    _use_dwh_var.set(use_dwh)
    response = get_query_runner(source, insight.team, modifiers=deepcopy(modifiers)).calculate()
    return response.results or []


def _check_one(insight: Insight, url: str, freeze: bool) -> Row:
    try:
        action, reason = classify_insight(insight)
        if action == "error":
            return Row(insight.short_id, insight.team_id, url, "ERROR", reason)
        if action == "skip":
            return Row(insight.short_id, insight.team_id, url, "SKIPPED", reason)

        modifiers = create_default_modifiers_for_team(insight.team, HogQLQueryModifiers())
        ctx = compute_interval_context(insight, modifiers, freeze=freeze)
        override = ctx.frozen_date_range

        legacy = _run_variant(insight, False, modifiers, override)
        dwh = _run_variant(insight, True, modifiers, override)
        diff = diff_retention_results(
            legacy,
            dwh,
            latest_interval_start=ctx.latest_interval_start,
            interval_delta=ctx.trailing_delta,
        )
        detail = ""
        if diff.status == "MISMATCH":
            detail = (
                f"{len(diff.cell_diffs)} cell diff(s), rows legacy={diff.row_count_legacy} dwh={diff.row_count_dwh}"
            )
        return Row(insight.short_id, insight.team_id, url, diff.status, detail)
    except Exception as exc:
        return Row(insight.short_id, insight.team_id, url, "ERROR", f"{type(exc).__name__}: {exc}")


def _check_team(
    insights: list[Insight], urls: dict[int, str], freeze: bool, report: Callable[[Row], None]
) -> list[Row]:
    """One lane = one team. Its insights are checked serially so a team's data is never read
    concurrently with itself; distinct teams run in parallel across lanes."""
    rows: list[Row] = []
    try:
        for insight in insights:
            row = _check_one(insight, urls[insight.id], freeze)
            rows.append(row)
            report(row)
    finally:
        # This lane's worker thread opened its own Django DB connection lazily; close it so a large
        # fan-out across teams does not exhaust the Postgres connection pool.
        connections.close_all()
    return rows


class Command(BaseCommand):
    help = "Fast correctness-only comparison of legacy vs DWH retention variant (no perf, concurrent)"

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--team-id", type=int, action="append", help="Restrict to team id(s); repeatable")
        parser.add_argument("--insight-id", type=int, action="append", help="Restrict to insight DB id(s); repeatable")
        parser.add_argument("--short-id", type=str, action="append", help="Restrict to insight short_id(s); repeatable")
        parser.add_argument("--limit", type=int, default=100, help="Max insights to process (default 100)")
        parser.add_argument("--sample", type=int, default=None, help="Randomly sample N insights instead of by date")
        parser.add_argument(
            "--concurrency",
            type=int,
            default=8,
            help="Distinct teams checked in parallel (default 8; 1 = serial). A team's own insights are "
            "always checked serially, so two concurrent queries never read the same team's data.",
        )
        parser.add_argument("--base-url", type=str, default="https://us.posthog.com", help="Base URL for insight links")
        parser.add_argument(
            "--freeze-window",
            "--exclude-current-period",
            dest="freeze_window",
            action="store_true",
            help="Compare over a frozen snapshot ending at the last complete interval (drops the in-progress period)",
        )
        parser.add_argument("--fail-on-mismatch", action="store_true", help="Exit non-zero if any MISMATCH is found")

    def handle(self, *args: Any, **options: Any) -> None:
        insights = self._select_insights(options)
        if not insights:
            self.stdout.write(self.style.WARNING("No retention insights matched the given filters."))
            return

        base_url = options["base_url"].rstrip("/")
        freeze = options["freeze_window"]
        urls = {i.id: f"{base_url}/project/{i.team_id}/insights/{i.short_id}/edit" for i in insights}

        # One lane per team: the team's insights run serially within the lane, distinct teams in
        # parallel — so concurrent queries always read different teams' data, never the same team's.
        teams: dict[int, list[Insight]] = defaultdict(list)
        for insight in insights:
            teams[insight.team_id].append(insight)
        concurrency = max(1, min(options["concurrency"], len(teams)))
        self.stdout.write(
            f"Checking {len(insights)} retention insight(s) across {len(teams)} team(s), "
            f"up to {concurrency} team(s) in parallel…"
        )

        total = len(insights)
        progress_lock = threading.Lock()
        done = 0

        def report(row: Row) -> None:
            nonlocal done
            with progress_lock:
                done += 1
                self._print_progress(done, total, row)

        rows: list[Row] = []
        # One process-wide patch; each worker selects its variant via the ContextVar.
        with patch(RETENTION_BASE_QUERY_VARIANT_PATCH_PATH, side_effect=lambda team: _use_dwh_var.get()):
            with ThreadPoolExecutor(max_workers=concurrency) as pool:
                futures = [
                    pool.submit(_check_team, team_insights, urls, freeze, report) for team_insights in teams.values()
                ]
                for future in as_completed(futures):
                    rows.extend(future.result())

        self._print_summary(rows)

        mismatches = sum(1 for r in rows if r.status == "MISMATCH")
        if options["fail_on_mismatch"] and mismatches:
            raise CommandError(f"{mismatches} insight(s) mismatched between variants")

    def _select_insights(self, options: dict[str, Any]) -> list[Insight]:
        queryset = Insight.objects.filter(saved=True, deleted=False, query__source__kind="RetentionQuery")
        if options["team_id"]:
            queryset = queryset.filter(team_id__in=options["team_id"])
        if options["insight_id"]:
            queryset = queryset.filter(id__in=options["insight_id"])
        if options["short_id"]:
            queryset = queryset.filter(short_id__in=options["short_id"])
        queryset = queryset.select_related("team")
        if options["sample"]:
            return list(queryset.order_by("?")[: options["sample"]])
        return list(queryset.order_by("created_at")[: options["limit"]])

    def _print_progress(self, done: int, total: int, row: Row) -> None:
        if row.status == "OK":
            return  # keep the stream quiet; only surface the interesting outcomes
        style = {"MISMATCH": self.style.ERROR, "ERROR": self.style.ERROR}.get(row.status, self.style.WARNING)
        suffix = f" — {row.detail}" if row.detail else ""
        self.stdout.write(style(f"[{done}/{total}] {row.status} {row.short_id} (team {row.team_id}){suffix}"))

    def _print_summary(self, rows: list[Row]) -> None:
        counts = {
            status: sum(1 for r in rows if r.status == status) for status in ("OK", "MISMATCH", "ERROR", "SKIPPED")
        }
        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("Summary"))
        self.stdout.write(
            f"OK={counts['OK']} MISMATCH={counts['MISMATCH']} ERROR={counts['ERROR']} SKIPPED={counts['SKIPPED']}"
        )
        mismatches = [r for r in rows if r.status == "MISMATCH"]
        if mismatches:
            self.stdout.write(self.style.ERROR("\nMismatches:"))
            for r in mismatches:
                self.stdout.write(self.style.ERROR(f"  {r.short_id} (team {r.team_id}) {r.url} — {r.detail}"))
        sys.stdout.flush()
