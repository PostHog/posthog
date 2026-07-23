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

Failures are attributed per variant: each side runs under its own guard, so an insight is reported
as ERROR_DWH (legacy succeeded, the variant failed — a regression candidate that gates rollout),
ERROR_LEGACY (the variant fixes an insight that is broken today), or ERROR_BOTH (parity-in-failure:
broken regardless of the toggle). Plain ERROR is reserved for failures outside the two variant runs.
Insights whose referenced actions/cohorts were deleted are SKIPPED up front by ``classify_insight``
instead of erroring on both sides. A first-pass mismatch is re-run once and only the differences
that reproduce are kept (``--no-recheck-mismatches`` to disable): late-arriving events and person
merges move *historical* buckets between the two sequential runs, so a single pass can report live
drift as a parity bug.

The variant toggle is process-global, so instead of nesting a ``patch`` per call (which would race
across worker threads) we install one process-wide patch whose return value is read from a
``ContextVar`` each worker sets before it runs. Threads start with a fresh context, so the workers
never collide.

Checking *all* insights is done as a resumable sweep, not one giant run. Pass ``--state-file
progress.json`` and the command processes one ``--limit``-sized batch, writes a cursor (the highest
insight id it reached) plus the running counts and accumulated findings back to that file, then exits.
Re-run the same command and it resumes just past the cursor; repeat until it reports the sweep complete.
The cursor is printed every run, so without a state file you can drive the same loop by hand with
``--after-id``. It is a keyset cursor (``id > cursor``), not a row offset — concurrent inserts or
deletes between runs never make it skip or re-check an insight, which a numeric offset would. The state
file is tied to the filter set it was created with (``--team-id`` etc.); reusing it under a different
scope is refused so a narrowed cursor can't silently leave insights unchecked.

Examples:
    # All retention insights, up to 8 teams in parallel
    python manage.py compare_retention_correctness

    # Resumable sweep over every insight: run this repeatedly until it reports "complete"
    python manage.py compare_retention_correctness --state-file /tmp/retention_sweep.json --limit 500

    # Drive the cursor by hand (no state file): each run prints the --after-id for the next
    python manage.py compare_retention_correctness --limit 500 --after-id 0

    # One team, serial (e.g. to avoid extra ClickHouse load on prod)
    python manage.py compare_retention_correctness --team-id 42 --concurrency 1

    # CI gate: non-zero exit if anything mismatches
    python manage.py compare_retention_correctness --fail-on-mismatch
"""

import os
import sys
import json
import argparse
import threading
import contextvars
import dataclasses
from collections import defaultdict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from datetime import UTC, datetime
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
    attribute_variant_errors,
    classify_insight,
    compute_interval_context,
    diff_retention_results,
    intersect_stable_mismatch,
)

from products.product_analytics.backend.models.insight import Insight

# Per-thread variant selector. The single process-wide patch below reads this, so concurrent
# workers each pick their own variant without stepping on a shared global.
_use_dwh_var: contextvars.ContextVar[bool] = contextvars.ContextVar("retention_use_dwh", default=False)


PROGRESS_STATUSES = ("OK", "MISMATCH", "ERROR", "ERROR_LEGACY", "ERROR_DWH", "ERROR_BOTH", "SKIPPED")


@dataclasses.dataclass
class Row:
    id: int
    short_id: str
    team_id: int
    url: str
    status: str  # one of PROGRESS_STATUSES
    detail: str = ""


@dataclasses.dataclass
class ProgressState:
    """Resumable-sweep checkpoint, persisted as JSON between runs.

    ``cursor`` is a keyset position: the next run checks insights with ``id`` greater than it. Counts and
    findings accumulate across runs, so a completed file is itself the full report. ``scope`` fingerprints
    the filter set the sweep was started with, so resuming under different filters can be refused.
    """

    cursor: int = 0  # highest insight id checked so far; next run filters id > cursor
    processed: int = 0  # cumulative insights checked across all runs
    counts: dict[str, int] = dataclasses.field(default_factory=lambda: dict.fromkeys(PROGRESS_STATUSES, 0))
    mismatches: list[dict[str, Any]] = dataclasses.field(default_factory=list)
    errors: list[dict[str, Any]] = dataclasses.field(default_factory=list)
    complete: bool = False
    scope: str = ""
    updated_at: Optional[str] = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProgressState":
        raw_counts = data.get("counts") or {}
        return cls(
            cursor=int(data.get("cursor", 0)),
            processed=int(data.get("processed", 0)),
            counts={s: int(raw_counts.get(s, 0)) for s in PROGRESS_STATUSES},
            mismatches=list(data.get("mismatches") or []),
            errors=list(data.get("errors") or []),
            complete=bool(data.get("complete", False)),
            scope=str(data.get("scope", "")),
            updated_at=data.get("updated_at"),
        )

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


def _row_record(row: Row) -> dict[str, Any]:
    return {
        "id": row.id,
        "short_id": row.short_id,
        "team_id": row.team_id,
        "url": row.url,
        "status": row.status,
        "detail": row.detail,
    }


def merge_progress_state(
    prev: Optional[ProgressState],
    rows: list[Row],
    *,
    next_cursor: Optional[int],
    limit: int,
    scope: str = "",
) -> ProgressState:
    """Fold one batch's rows into the running checkpoint. Pure — no IO, no clock, never mutates ``prev``.

    ``next_cursor`` is the highest insight id covered by the batch (``None`` when the batch was empty, e.g.
    the sweep ran off the end). The sweep is ``complete`` once a batch returns fewer rows than ``limit``,
    i.e. the source is exhausted. The cursor only ever advances.
    """
    base = prev or ProgressState(scope=scope)
    counts = dict(base.counts)
    for status in PROGRESS_STATUSES:
        counts[status] = counts.get(status, 0) + sum(1 for r in rows if r.status == status)
    return ProgressState(
        cursor=max(base.cursor, next_cursor) if next_cursor is not None else base.cursor,
        processed=base.processed + len(rows),
        counts=counts,
        mismatches=base.mismatches + [_row_record(r) for r in rows if r.status == "MISMATCH"],
        # All attributed variants (ERROR_LEGACY / ERROR_DWH / ERROR_BOTH) accumulate here too.
        errors=base.errors + [_row_record(r) for r in rows if r.status.startswith("ERROR")],
        complete=len(rows) < limit,
        scope=scope or base.scope,
    )


def scope_signature(options: dict[str, Any]) -> str:
    """Stable fingerprint of the filters that define the insight universe and result comparability.

    Two runs sharing a state file must agree on this, otherwise the saved cursor could skip insights the
    new scope cares about (or mix frozen and live results in the accumulated findings).
    """
    return json.dumps(
        {
            "team_id": sorted(options.get("team_id") or []),
            "insight_id": sorted(options.get("insight_id") or []),
            "short_id": sorted(options.get("short_id") or []),
            "freeze_window": bool(options.get("freeze_window")),
            # Changes what MISMATCH means (stability-filtered vs raw), so accumulated findings
            # from runs with different settings must not mix in one sweep.
            "recheck_mismatches": bool(options.get("recheck_mismatches", True)),
        },
        sort_keys=True,
    )


def load_progress_state(path: str) -> Optional[ProgressState]:
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return ProgressState.from_dict(json.load(f))


def save_progress_state(path: str, state: ProgressState) -> None:
    # Write-then-replace so a crash mid-write can't corrupt an in-progress sweep's checkpoint.
    tmp = f"{path}.tmp"
    with open(tmp, "w") as f:
        json.dump(state.to_dict(), f, indent=2, sort_keys=True)
    os.replace(tmp, path)


def _run_variant(
    insight: Insight, use_dwh: bool, modifiers: HogQLQueryModifiers, override: Optional[dict[str, Any]]
) -> list:
    assert insight.query is not None  # classify_insight has already validated the query shape
    source = deepcopy(insight.query["source"])
    if override is not None:
        source["dateRange"] = override
    _use_dwh_var.set(use_dwh)
    response = get_query_runner(source, insight.team, modifiers=deepcopy(modifiers)).calculate()
    return response.results or []


def _try_variant(
    insight: Insight, use_dwh: bool, modifiers: HogQLQueryModifiers, override: Optional[dict[str, Any]]
) -> tuple[Optional[list], Optional[BaseException]]:
    try:
        return _run_variant(insight, use_dwh, modifiers, override), None
    except Exception as exc:
        return None, exc


def _check_one(insight: Insight, url: str, freeze: bool, recheck: bool) -> Row:
    try:
        action, reason = classify_insight(insight)
        if action == "error":
            return Row(insight.id, insight.short_id, insight.team_id, url, "ERROR", reason)
        if action == "skip":
            return Row(insight.id, insight.short_id, insight.team_id, url, "SKIPPED", reason)

        modifiers = create_default_modifiers_for_team(insight.team, HogQLQueryModifiers())
        ctx = compute_interval_context(insight, modifiers, freeze=freeze)
        override = ctx.frozen_date_range

        # Per-variant guards so a failure is attributed to the side that raised it (ERROR_DWH /
        # ERROR_LEGACY / ERROR_BOTH) instead of one opaque ERROR that hides which side broke.
        legacy, legacy_exc = _try_variant(insight, False, modifiers, override)
        dwh, dwh_exc = _try_variant(insight, True, modifiers, override)
        if legacy_exc is not None or dwh_exc is not None:
            status, _error_type, summary = attribute_variant_errors(legacy_exc, dwh_exc)
            return Row(insight.id, insight.short_id, insight.team_id, url, status, summary)
        assert legacy is not None and dwh is not None

        diff_kwargs: dict[str, Any] = {
            "latest_interval_start": ctx.latest_interval_start,
            "interval_delta": ctx.trailing_delta,
        }
        diff = diff_retention_results(legacy, dwh, **diff_kwargs)

        # Re-run a first-pass mismatch once and keep only the differences that reproduce: live
        # ingest and person merges shift historical buckets between the sequential runs, so an
        # unrepeated diff is drift, not a parity bug. Bounded cost — mismatches only.
        rechecked = False
        if recheck and diff.status == "MISMATCH":
            legacy2, legacy2_exc = _try_variant(insight, False, modifiers, override)
            dwh2, dwh2_exc = _try_variant(insight, True, modifiers, override)
            if legacy2_exc is None and dwh2_exc is None:
                assert legacy2 is not None and dwh2 is not None
                diff = intersect_stable_mismatch(diff, diff_retention_results(legacy2, dwh2, **diff_kwargs))
                rechecked = True
            # On a recheck failure keep the (valid) first-pass verdict and say it's unverified.

        detail = ""
        if diff.status == "MISMATCH":
            stable = "stable " if rechecked else ""
            detail = (
                f"{len(diff.cell_diffs)} {stable}cell diff(s), "
                f"rows legacy={diff.row_count_legacy} dwh={diff.row_count_dwh}"
            )
            if recheck and not rechecked:
                detail += " (recheck errored — stability unverified)"
        return Row(insight.id, insight.short_id, insight.team_id, url, diff.status, detail)
    except Exception as exc:
        return Row(insight.id, insight.short_id, insight.team_id, url, "ERROR", f"{type(exc).__name__}: {exc}")


def _check_team(
    insights: list[Insight], urls: dict[int, str], freeze: bool, recheck: bool, report: Callable[[Row], None]
) -> list[Row]:
    """One lane = one team. Its insights are checked serially so a team's data is never read
    concurrently with itself; distinct teams run in parallel across lanes."""
    rows: list[Row] = []
    try:
        for insight in insights:
            row = _check_one(insight, urls[insight.id], freeze, recheck)
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
        parser.add_argument("--limit", type=int, default=100, help="Max insights per batch (default 100)")
        parser.add_argument("--sample", type=int, default=None, help="Randomly sample N insights instead of by id")
        parser.add_argument(
            "--state-file",
            type=str,
            default=None,
            help="JSON checkpoint for a resumable sweep. If it exists the run resumes from its saved cursor; "
            "afterwards it is rewritten with the new cursor plus accumulated counts and findings. Re-run the "
            "same command to walk every matching insight in --limit-sized batches until it reports complete.",
        )
        parser.add_argument(
            "--after-id",
            type=int,
            default=None,
            help="Resume cursor: only check insights with a DB id greater than this. Overrides the cursor in "
            "--state-file when both are given. Keyset, not a row offset — it never skips or repeats insights "
            "when rows are added or deleted between runs.",
        )
        parser.add_argument(
            "--restart",
            action="store_true",
            help="Ignore any existing --state-file and start the sweep over (the file is overwritten).",
        )
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
        parser.add_argument(
            "--recheck-mismatches",
            action=argparse.BooleanOptionalAction,
            default=True,
            help="Re-run both variants once on a mismatch and keep only differences that reproduce (default on)",
        )
        parser.add_argument("--fail-on-mismatch", action="store_true", help="Exit non-zero if any MISMATCH is found")

    def handle(self, *args: Any, **options: Any) -> None:
        if options["limit"] < 1:
            raise CommandError("--limit must be at least 1")

        state_file: Optional[str] = options["state_file"]
        after_id: Optional[int] = options["after_id"]
        scope = scope_signature(options)

        if options["sample"] is not None and (state_file or after_id is not None):
            raise CommandError(
                "--sample picks a random set and can't drive a resumable sweep (--state-file / --after-id)."
            )

        prev_state, already_complete = self._load_resume_state(state_file, scope, after_id, options["restart"])
        if already_complete:
            return

        # Explicit --after-id wins; otherwise resume from the saved checkpoint (None = start from the top).
        cursor = after_id if after_id is not None else (prev_state.cursor if prev_state else None)

        insights = self._select_insights(options, after_id=cursor)
        if not insights:
            self._handle_empty(options, state_file, scope, prev_state, cursor)
            return

        rows = self._run(
            insights,
            options["base_url"].rstrip("/"),
            options["freeze_window"],
            options["recheck_mismatches"],
            options["concurrency"],
        )
        self._print_summary(rows)

        next_cursor = max(i.id for i in insights)
        if state_file:
            new_state = merge_progress_state(
                prev_state, rows, next_cursor=next_cursor, limit=options["limit"], scope=scope
            )
            new_state.updated_at = datetime.now(UTC).isoformat()
            save_progress_state(state_file, new_state)
            self._print_checkpoint(state_file, new_state)
            self._print_cumulative(new_state)
        else:
            self._print_next_cursor(next_cursor, len(insights), options["limit"])

        mismatches = sum(1 for r in rows if r.status == "MISMATCH")
        if options["fail_on_mismatch"] and mismatches:
            raise CommandError(f"{mismatches} insight(s) mismatched between variants")

    def _load_resume_state(
        self, state_file: Optional[str], scope: str, after_id: Optional[int], restart: bool
    ) -> tuple[Optional[ProgressState], bool]:
        """Load the checkpoint to resume from. The bool is ``True`` when the caller should stop because the
        sweep in ``state_file`` is already finished (and no explicit ``--after-id`` is forcing a re-run)."""
        if not state_file or restart:
            return None, False
        prev = load_progress_state(state_file)
        if prev is None:
            return None, False
        if prev.scope and prev.scope != scope:
            raise CommandError(
                f"State file {state_file} was written for a different filter set. "
                "Use a separate --state-file, or pass --restart to overwrite it."
            )
        if prev.complete and after_id is None:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Sweep already complete: {prev.processed} insight(s) checked, cursor at id {prev.cursor}. "
                    "Pass --restart to run it again."
                )
            )
            self._print_cumulative(prev)
            return prev, True
        return prev, False

    def _handle_empty(
        self,
        options: dict[str, Any],
        state_file: Optional[str],
        scope: str,
        prev_state: Optional[ProgressState],
        cursor: Optional[int],
    ) -> None:
        """Nothing left to check: either the filters match nothing or the sweep just ran off the end."""
        if state_file:
            new_state = merge_progress_state(prev_state, [], next_cursor=None, limit=options["limit"], scope=scope)
            new_state.updated_at = datetime.now(UTC).isoformat()
            save_progress_state(state_file, new_state)
            self.stdout.write(
                self.style.SUCCESS(
                    f"No insights past cursor id {cursor or 0} — sweep complete after {new_state.processed} insight(s)."
                )
            )
            self._print_cumulative(new_state)
        elif cursor is not None:
            self.stdout.write(self.style.SUCCESS(f"No insights past id {cursor} — nothing left to check."))
        else:
            self.stdout.write(self.style.WARNING("No retention insights matched the given filters."))

    def _run(
        self, insights: list[Insight], base_url: str, freeze: bool, recheck: bool, concurrency_opt: int
    ) -> list[Row]:
        urls = {i.id: f"{base_url}/project/{i.team_id}/insights/{i.short_id}/edit" for i in insights}

        # One lane per team: the team's insights run serially within the lane, distinct teams in
        # parallel — so concurrent queries always read different teams' data, never the same team's.
        teams: dict[int, list[Insight]] = defaultdict(list)
        for insight in insights:
            teams[insight.team_id].append(insight)
        concurrency = max(1, min(concurrency_opt, len(teams)))
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
                    pool.submit(_check_team, team_insights, urls, freeze, recheck, report)
                    for team_insights in teams.values()
                ]
                for future in as_completed(futures):
                    rows.extend(future.result())
        return rows

    def _select_insights(self, options: dict[str, Any], after_id: Optional[int] = None) -> list[Insight]:
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
        # Keyset pagination: ascending id is a stable, unique sweep order and the cursor is just the last id.
        if after_id is not None:
            queryset = queryset.filter(id__gt=after_id)
        return list(queryset.order_by("id")[: options["limit"]])

    def _print_progress(self, done: int, total: int, row: Row) -> None:
        if row.status == "OK":
            return  # keep the stream quiet; only surface the interesting outcomes
        is_bad = row.status == "MISMATCH" or row.status.startswith("ERROR")
        style = self.style.ERROR if is_bad else self.style.WARNING
        suffix = f" — {row.detail}" if row.detail else ""
        self.stdout.write(style(f"[{done}/{total}] {row.status} {row.short_id} (team {row.team_id}){suffix}"))

    def _print_summary(self, rows: list[Row]) -> None:
        counts = {status: sum(1 for r in rows if r.status == status) for status in PROGRESS_STATUSES}
        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("Summary"))
        self.stdout.write(" ".join(f"{status}={counts[status]}" for status in PROGRESS_STATUSES))
        mismatches = [r for r in rows if r.status == "MISMATCH"]
        if mismatches:
            self.stdout.write(self.style.ERROR("\nMismatches:"))
            for r in mismatches:
                self.stdout.write(self.style.ERROR(f"  {r.short_id} (team {r.team_id}) {r.url} — {r.detail}"))
        dwh_only = [r for r in rows if r.status == "ERROR_DWH"]
        if dwh_only:
            self.stdout.write(self.style.ERROR("\nDWH-only errors (variant regression candidates):"))
            for r in dwh_only:
                self.stdout.write(self.style.ERROR(f"  {r.short_id} (team {r.team_id}) {r.url} — {r.detail}"))
        sys.stdout.flush()

    def _print_next_cursor(self, next_cursor: int, batch_size: int, limit: int) -> None:
        self.stdout.write("")
        if batch_size < limit:
            self.stdout.write(self.style.SUCCESS(f"Reached the end of the set (last insight id {next_cursor})."))
        else:
            self.stdout.write(f"Next cursor: {next_cursor}. Continue the sweep with --after-id {next_cursor}")

    def _print_checkpoint(self, state_file: str, state: ProgressState) -> None:
        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("Sweep progress"))
        counts_line = " ".join(f"{status}={state.counts.get(status, 0)}" for status in PROGRESS_STATUSES)
        self.stdout.write(f"Checked {state.processed} insight(s) so far — {counts_line}")
        self.stdout.write(f"Checkpoint written to {state_file} (cursor at insight id {state.cursor}).")
        if state.complete:
            self.stdout.write(self.style.SUCCESS("Sweep complete — every matching insight has been checked."))
        else:
            self.stdout.write("Re-run the same command to check the next batch (resumes from this cursor).")

    def _print_cumulative(self, state: ProgressState) -> None:
        """List the findings accumulated across the whole sweep so far (capped; the full set is in the file)."""
        self._print_record_list("Accumulated mismatches", state.mismatches, self.style.ERROR)
        self._print_record_list("Accumulated errors", state.errors, self.style.WARNING)

    def _print_record_list(self, heading: str, records: list[dict[str, Any]], style: Callable[[str], str]) -> None:
        if not records:
            return
        cap = 50
        self.stdout.write(style(f"\n{heading} ({len(records)}):"))
        for rec in records[:cap]:
            # Attribution matters within the errors list; older state files have no status field.
            label = f"[{rec['status']}] " if rec.get("status", "").startswith("ERROR") else ""
            detail = f" — {rec['detail']}" if rec.get("detail") else ""
            self.stdout.write(style(f"  {label}{rec['short_id']} (team {rec['team_id']}) {rec['url']}{detail}"))
        if len(records) > cap:
            self.stdout.write(style(f"  …and {len(records) - cap} more (see state file)"))
