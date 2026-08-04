"""Fast correctness-only check: legacy vs new ("DWH variant") retention base query.

A stripped-down companion to ``compare_retention_legacy_vs_dwh``: no timing, no query-log
resource stats, no HogQL embedding, no per-insight report blocks. It runs each affected
RetentionQuery insight twice (variant OFF then ON), diffs the two result sets, and prints a
one-line-per-mismatch summary. A heartbeat line every 10 insights shows elapsed time, ETA, and the
running counts, so a long healthy (all-OK) run still shows liveness. The expensive parts of the
full tool are gone and insights are checked concurrently, so a correctness sweep finishes in a
fraction of the time.

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
drift as a parity bug. The recheck runs the variants in reversed order (dwh before legacy) so that
replica part-set divergence — replicas mid-way through applying the same rewrites can serve
different data for minutes, and a fixed query cadence phase-locks each variant onto one replica
state — shows up as moved values (churn) rather than masquerading as a value-identical
deterministic difference.

Mismatches also age: when a sweep run starts (or an already-complete sweep is re-run) with a
``--state-file``, every previously accumulated mismatch is first re-verified against current data.
Ones that no longer reproduce move to a ``resolved_mismatches`` list — typically artifacts of data
that was being rewritten (merge campaigns collapsing re-emitted rows) when the original batch ran —
and the counts move from MISMATCH to the settled status. Only differences that keep reproducing
across runs, usually hours apart, stay in the report.

The variant toggle is process-global, so instead of nesting a ``patch`` per call (which would race
across worker threads) we install one process-wide patch whose return value is read from a
``ContextVar`` each worker sets before it runs. Threads start with a fresh context, so the workers
never collide.

Checking *all* insights can be one giant run (``--all``, which ignores ``--limit``) or a resumable
sweep. For the sweep, pass ``--state-file progress.json`` and the command processes one
``--limit``-sized batch, writes a cursor (the highest
insight id it reached) plus the running counts and accumulated findings back to that file, then exits.
Re-run the same command and it resumes just past the cursor; repeat until it reports the sweep complete.
The cursor is printed every run, so without a state file you can drive the same loop by hand with
``--after-id``. It is a keyset cursor (``id > cursor``), not a row offset — concurrent inserts or
deletes between runs never make it skip or re-check an insight, which a numeric offset would. The state
file is tied to the filter set it was created with (``--team-id`` etc.); reusing it under a different
scope is refused so a narrowed cursor can't silently leave insights unchecked.

With a ``--state-file``, interrupting a run (Ctrl-C, pod eviction) loses nothing: every finished
insight is also appended to ``<state-file>.journal`` the moment it completes, and the next run skips
the journaled insights and folds their recorded results into the report — so ``--all --state-file
sweep.json`` is a single resumable run. The journal is absorbed into the state file when a batch
finishes. The cursor alone can't provide this: teams run in parallel lanes, so an interrupted run's
completed ids are scattered across the id range, not a contiguous prefix a cursor could describe.
A resumed run says so up front (recovered and remaining counts) and its progress counter and status
totals continue from the recovered position instead of restarting at zero; only the ETA rate comes
from insights this run finished itself. The checkpoint file is also written the moment a run starts,
so the key exists (and names the active writer) mid-sweep — until a batch completes it records no
progress, which lives in the journal.

Pods are ephemeral, so a state file on the pod's own disk dies with the pod. Prefix ``--state-file``
with ``s3://`` (e.g. ``s3://retention_compare/sweep.json``, a key in the default object-storage
bucket) to keep the checkpoint and journal in object storage instead: any other pod with the same
command then resumes the sweep. Object storage can't append, so the remote journal is uploaded whole
at most every ~30s and on SIGTERM (evictions grant a grace period); a hard kill (OOM) loses at most
that window of finished insights, which the resumed run simply re-checks. The state file records
which host last wrote it, and resuming from a different host prints a notice, since nothing stops
two pods from writing the same key.

Examples:
    # All retention insights, up to 8 teams in parallel
    python manage.py compare_retention_correctness

    # Every matching insight in one run; Ctrl-C safe — re-run the same command to resume
    python manage.py compare_retention_correctness --all --state-file /tmp/retention_sweep.json

    # Same, but the state survives the pod: resume from any other pod with the same command
    python manage.py compare_retention_correctness --all --state-file s3://retention_compare/sweep.json

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
import socket
import argparse
import threading
import contextvars
import dataclasses
from collections import Counter, defaultdict
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import nullcontext
from copy import deepcopy
from datetime import UTC, datetime
from time import perf_counter
from typing import Any, Optional

from unittest.mock import patch

from django.core.management.base import BaseCommand, CommandError
from django.db import connections

from posthog.schema import HogQLQueryModifiers

from posthog.hogql.modifiers import create_default_modifiers_for_team

from posthog.hogql_queries.query_runner import get_query_runner

# The patch path comes from the sibling command (which defines it locally, not via import) so this
# pair of files stays runnable when copied onto a prod pod regardless of the image's vintage.
from posthog.management.commands.compare_retention_legacy_vs_dwh import (
    HEARTBEAT_EVERY,
    RETENTION_BASE_QUERY_VARIANT_PATCH_PATH,
    FileLineSink,
    LineSink,
    ObjectStorageLineSink,
    _fmt_duration,
    attribute_variant_errors,
    classify_insight,
    compute_interval_context,
    delete_state_path,
    diff_retention_results,
    flush_on_sigterm,
    intersect_stable_mismatch,
    is_object_storage_path,
    object_storage_key,
    read_state_text,
    write_state_text,
)

from products.product_analytics.backend.models.insight import Insight

# Per-thread variant selector. The single process-wide patch below reads this, so concurrent
# workers each pick their own variant without stepping on a shared global.
_use_dwh_var: contextvars.ContextVar[bool] = contextvars.ContextVar("retention_use_dwh", default=False)


PROGRESS_STATUSES = ("OK", "MISMATCH", "ERROR", "ERROR_LEGACY", "ERROR_DWH", "ERROR_BOTH", "SKIPPED")

JOURNAL_SUFFIX = ".journal"


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
    ``writer`` is the host that last saved the checkpoint: a shared (object-storage) state file has no
    locking, so a resume from a different host prints a notice in case the previous pod is still running.
    """

    cursor: int = 0  # highest insight id checked so far; next run filters id > cursor
    processed: int = 0  # cumulative insights checked across all runs
    counts: dict[str, int] = dataclasses.field(default_factory=lambda: dict.fromkeys(PROGRESS_STATUSES, 0))
    mismatches: list[dict[str, Any]] = dataclasses.field(default_factory=list)
    # Mismatches from earlier batches that stopped reproducing when re-verified on a later run
    # (data settled), annotated with a "resolution" field.
    resolved_mismatches: list[dict[str, Any]] = dataclasses.field(default_factory=list)
    errors: list[dict[str, Any]] = dataclasses.field(default_factory=list)
    complete: bool = False
    scope: str = ""
    writer: str = ""
    updated_at: Optional[str] = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProgressState":
        raw_counts = data.get("counts") or {}
        return cls(
            cursor=int(data.get("cursor", 0)),
            processed=int(data.get("processed", 0)),
            counts={s: int(raw_counts.get(s, 0)) for s in PROGRESS_STATUSES},
            mismatches=list(data.get("mismatches") or []),
            resolved_mismatches=list(data.get("resolved_mismatches") or []),
            errors=list(data.get("errors") or []),
            complete=bool(data.get("complete", False)),
            scope=str(data.get("scope", "")),
            writer=str(data.get("writer", "")),
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
    complete: bool,
    scope: str = "",
) -> ProgressState:
    """Fold one batch's rows into the running checkpoint. Pure — no IO, no clock, never mutates ``prev``.

    ``next_cursor`` is the highest insight id covered so far (``None`` when nothing new was covered, e.g.
    the sweep ran off the end). ``complete`` — the fresh selection came up short of ``--limit``, i.e. the
    source is exhausted — is decided by the caller, because ``rows`` may also carry journal-recovered rows
    from an interrupted run, so its length says nothing about exhaustion. The cursor only ever advances.
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
        resolved_mismatches=base.resolved_mismatches,
        # All attributed variants (ERROR_LEGACY / ERROR_DWH / ERROR_BOTH) accumulate here too.
        errors=base.errors + [_row_record(r) for r in rows if r.status.startswith("ERROR")],
        complete=complete,
        scope=scope or base.scope,
    )


def revalidate_mismatches(
    records: list[dict[str, Any]],
    counts: dict[str, int],
    check: Callable[[dict[str, Any]], Optional[Row]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
    """Re-verify previously recorded mismatches against current data. Pure — inputs are not mutated.

    A batch runs minutes to hours after the batch that recorded a mismatch. A difference that was an
    artifact of data in motion (merges collapsing re-emitted rows while replicas serve divergent part
    sets) has converged by then and stops reproducing; a genuine query-semantics difference keeps
    reproducing. Returns (still_mismatched, resolved, adjusted_counts):

    - re-checks OK, or SKIPPED, or the insight is gone → resolved, annotated with a "resolution"
    - still MISMATCH → kept, with the detail refreshed to the latest verdict
    - re-check errored → kept untouched (no evidence either way; the next run retries)

    ``adjusted_counts`` moves each resolved record from MISMATCH to its settled status so the sweep
    totals reflect final verdicts.
    """
    kept: list[dict[str, Any]] = []
    resolved: list[dict[str, Any]] = []
    new_counts = dict(counts)

    def resolve(rec: dict[str, Any], status: str, resolution: str) -> None:
        new_counts["MISMATCH"] = max(0, new_counts.get("MISMATCH", 0) - 1)
        new_counts[status] = new_counts.get(status, 0) + 1
        resolved.append({**rec, "resolution": resolution})

    for rec in records:
        row = check(rec)
        if row is None:
            resolve(rec, "SKIPPED", "insight no longer exists")
        elif row.status == "OK":
            resolve(rec, "OK", "no longer reproduces (data settled)")
        elif row.status == "SKIPPED":
            resolve(rec, "SKIPPED", f"now skipped: {row.detail}")
        elif row.status == "MISMATCH":
            kept.append({**rec, "detail": row.detail})
        else:
            kept.append(rec)
    return kept, resolved, new_counts


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


def journal_line(row: Row) -> str:
    return json.dumps(_row_record(row))


def parse_journal_lines(lines: list[str], scope: str) -> list[Row]:
    """Decode the rows journaled by an interrupted run. Pure.

    The first line is a scope header; a mismatch raises ``ValueError`` so results from a
    differently-filtered run can't be folded into this sweep. Undecodable row lines (a write torn by
    the interrupt) are dropped — the worst case is re-checking that one insight. On a duplicate id
    the latest record wins, so a re-checked insight is only counted once.
    """
    if not lines:
        return []
    try:
        header = json.loads(lines[0])
    except ValueError:
        raise ValueError("journal header is unreadable")
    if not isinstance(header, dict) or "scope" not in header:
        raise ValueError("journal has no scope header")
    if header["scope"] != scope:
        raise ValueError("journal was written for a different filter set")
    rows: dict[int, Row] = {}
    for line in lines[1:]:
        try:
            row = Row(**json.loads(line))
        except (ValueError, TypeError):
            continue
        rows[row.id] = row
    return list(rows.values())


def load_progress_state(path: str) -> Optional[ProgressState]:
    text = read_state_text(path)
    if text is None:
        return None
    return ProgressState.from_dict(json.loads(text))


def save_progress_state(path: str, state: ProgressState) -> None:
    write_state_text(path, json.dumps(state.to_dict(), indent=2, sort_keys=True))


def stamp_progress_state(state: ProgressState) -> ProgressState:
    state.updated_at = datetime.now(UTC).isoformat()
    state.writer = socket.gethostname()
    return state


def unabsorbed_journal_rows(rows: list[Row], cursor: Optional[int]) -> list[Row]:
    """Journal rows not yet folded into the checkpoint. Pure.

    A journal normally disappears when its batch completes (the absorb deletes it right after the
    state write). If that delete never lands — a crash between the two writes, or an object-storage
    delete failing — the next run would fold the leftover rows a second time and double-count every
    one of them. Absorbed rows are exactly those at or below the checkpoint cursor: a batch only
    journals ids above the cursor it started from, and the cursor only advances when a batch's rows
    are absorbed.
    """
    if cursor is None:
        return rows
    return [row for row in rows if row.id > cursor]


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
        #
        # The recheck runs the variants in REVERSED order (dwh first). Consecutive queries can be
        # served from different replicas whose part sets diverge while data is being rewritten
        # (e.g. merges collapsing re-emitted person-merge rows), and a fixed legacy→dwh→legacy→dwh
        # cadence phase-locks each variant onto one replica state — the skew then reproduces
        # value-identically and reads as a deterministic query bug. Reversing the recheck order
        # flips which state each variant reads: replica skew surfaces as moved values (churn),
        # while a genuine query difference still reproduces with identical values.
        rechecked = False
        if recheck and diff.status == "MISMATCH":
            dwh2, dwh2_exc = _try_variant(insight, True, modifiers, override)
            legacy2, legacy2_exc = _try_variant(insight, False, modifiers, override)
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
            if rechecked and diff.cell_diffs:
                # Value-identical cells reproduce exactly (deterministic difference); moved values
                # mean the data changed under the queries in both passes (merge/late-ingest churn).
                identical = sum(1 for c in diff.cell_diffs if c.values_stable)
                if identical:
                    detail += f", {identical}/{len(diff.cell_diffs)} value-identical (deterministic)"
                else:
                    detail += ", all values moved between passes (churn, not deterministic)"
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
        parser.add_argument("--all", action="store_true", help="Process every matching insight (ignores --limit)")
        parser.add_argument("--sample", type=int, default=None, help="Randomly sample N insights instead of by id")
        parser.add_argument(
            "--state-file",
            type=str,
            default=None,
            help="JSON checkpoint for a resumable sweep. If it exists the run resumes from its saved cursor; "
            "afterwards it is rewritten with the new cursor plus accumulated counts and findings. Re-run the "
            "same command to walk every matching insight in --limit-sized batches until it reports complete. "
            "Interrupted runs resume too: each finished insight is journaled to <state-file>.journal as it "
            "completes, and the next run skips the journaled insights and keeps their results. Prefix with "
            "s3:// to keep the checkpoint and journal in object storage (the key lands in the default "
            "bucket), so the sweep outlives an ephemeral pod and any other pod can resume it; the journal "
            "is uploaded every ~30s and on SIGTERM. The checkpoint file is created as soon as the run "
            "starts; mid-run progress lives in the journal until the batch completes.",
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

        if options["all"] and options["sample"]:
            raise CommandError("--all and --sample are mutually exclusive")

        if options["sample"] is not None and (state_file or after_id is not None):
            raise CommandError(
                "--sample picks a random set and can't drive a resumable sweep (--state-file / --after-id)."
            )

        prev_state, already_complete = self._load_resume_state(state_file, scope, after_id, options["restart"])
        journal_file = f"{state_file}{JOURNAL_SUFFIX}" if state_file else None
        journal_rows = self._load_journal(journal_file, scope, restart=options["restart"])
        journal_rows = unabsorbed_journal_rows(journal_rows, prev_state.cursor if prev_state else None)

        # Re-verify mismatches recorded by earlier batches before doing new work: enough time has
        # usually passed for in-motion data (merges, replica divergence) to settle, so artifacts
        # drop out of the accumulated findings and only reproducing differences stay. Re-running the
        # command on an already-complete sweep does just this re-verification.
        if state_file and prev_state is not None and prev_state.mismatches and options["recheck_mismatches"]:
            prev_state = self._revalidate_previous_mismatches(prev_state, options)
            save_progress_state(state_file, stamp_progress_state(prev_state))

        if already_complete:
            assert prev_state is not None  # already_complete implies a loaded checkpoint
            self._print_cumulative(prev_state)
            return

        # Explicit --after-id wins; otherwise resume from the saved checkpoint (None = start from the top).
        cursor = after_id if after_id is not None else (prev_state.cursor if prev_state else None)

        insights = self._select_insights(options, after_id=cursor, exclude_ids={r.id for r in journal_rows})
        if not insights:
            self._handle_empty(options, state_file, scope, prev_state, cursor, journal_rows, journal_file)
            return

        if journal_rows:
            total = len(journal_rows) + len(insights)
            self.stdout.write(
                f"Resuming: {len(journal_rows)}/{total} insight(s) already checked, {len(insights)} to go."
            )
        if state_file:
            # Claim the checkpoint up front. The only other write is at batch end — for --all the
            # end of the whole sweep — so until then the key would not exist and a mid-sweep look
            # at it reads as a run that never persisted anything. Claiming also records this host
            # as the active writer, and on --restart it replaces the finished checkpoint right
            # away, so a crashed restart resumes instead of reporting the old sweep complete.
            save_progress_state(state_file, stamp_progress_state(prev_state or ProgressState(scope=scope)))

        journal = self._open_journal(journal_file, scope, recovered=journal_rows)
        # A local journal flushes every row to disk, so only the buffering object-storage sink
        # needs the eviction (SIGTERM) flush.
        sigterm_guard = flush_on_sigterm(journal.flush) if isinstance(journal, ObjectStorageLineSink) else nullcontext()
        try:
            with sigterm_guard:
                rows = self._run(
                    insights,
                    options["base_url"].rstrip("/"),
                    options["freeze_window"],
                    options["recheck_mismatches"],
                    options["concurrency"],
                    journal,
                    recovered=journal_rows,
                )
        finally:
            if journal is not None:
                journal.close()
        all_rows = journal_rows + rows
        self._print_summary(all_rows)

        next_cursor = max(r.id for r in all_rows)
        # Exhaustion is judged on the fresh selection alone: --all drains everything past the
        # cursor, and journal-recovered rows don't count against the batch size.
        fresh_exhausted = options["all"] or len(insights) < options["limit"]
        if state_file:
            new_state = merge_progress_state(
                prev_state, all_rows, next_cursor=next_cursor, complete=fresh_exhausted, scope=scope
            )
            save_progress_state(state_file, stamp_progress_state(new_state))
            self._absorb_journal(journal_file)
            self._print_checkpoint(state_file, new_state)
            self._print_cumulative(new_state)
        else:
            self._print_next_cursor(next_cursor, fresh_exhausted)

        mismatches = sum(1 for r in all_rows if r.status == "MISMATCH")
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
            return prev, True
        # A shared state file has no locking; two writers would silently clobber each other's batches.
        if prev.writer and prev.writer != socket.gethostname():
            self.stdout.write(
                self.style.WARNING(
                    f"Resuming a sweep last written by {prev.writer} at {prev.updated_at or 'an unknown time'}. "
                    "Make sure that run is no longer active before continuing."
                )
            )
        return prev, False

    def _load_journal(self, path: Optional[str], scope: str, restart: bool) -> list[Row]:
        """Rows persisted per-insight by an interrupted run. They are excluded from this run's
        selection and their recorded results folded into the checkpoint when the batch completes."""
        if path is None:
            return []
        if restart:
            delete_state_path(path)
            return []
        text = read_state_text(path)
        if text is None:
            return []
        try:
            rows = parse_journal_lines(text.splitlines(), scope)
        except ValueError as exc:
            raise CommandError(f"{path}: {exc}. Use a separate --state-file, or pass --restart to overwrite it.")
        if rows:
            self.stdout.write(f"Recovered {len(rows)} finished insight(s) from the interrupted run in {path}.")
        return rows

    def _open_journal(self, path: Optional[str], scope: str, recovered: list[Row]) -> Optional[LineSink]:
        if path is None:
            return None
        if is_object_storage_path(path):
            # Every upload replaces the whole object, so the buffer must start with everything the
            # journal still needs to hold: the scope header plus the interrupted run's recovered
            # rows, which are only safe to drop once the batch-end absorb folds them into the
            # state file.
            lines = [json.dumps({"scope": scope}), *(journal_line(row) for row in recovered)]
            return ObjectStorageLineSink(object_storage_key(path), lines)
        handle = open(path, "a")
        if handle.tell() == 0:
            handle.write(json.dumps({"scope": scope}) + "\n")
        else:
            with open(path, "rb") as tail:
                tail.seek(-1, os.SEEK_END)
                ends_clean = tail.read(1) == b"\n"
            if not ends_clean:
                # The previous interrupt tore a write mid-line; start on a fresh line so the next
                # record isn't glued onto the fragment (which would corrupt both).
                handle.write("\n")
        handle.flush()
        return FileLineSink(handle)

    def _absorb_journal(self, path: Optional[str]) -> None:
        # The batch's rows are in the state file now; a leftover journal would double-fold them.
        if path is not None:
            delete_state_path(path)

    def _revalidate_previous_mismatches(self, state: ProgressState, options: dict[str, Any]) -> ProgressState:
        self.stdout.write(f"Re-verifying {len(state.mismatches)} previously recorded mismatch(es)…")
        freeze: bool = options["freeze_window"]

        def check(rec: dict[str, Any]) -> Optional[Row]:
            insight = (
                Insight.objects.filter(pk=rec["id"], saved=True, deleted=False, query__source__kind="RetentionQuery")
                .select_related("team")
                .first()
            )
            if insight is None:
                return None
            return _check_one(insight, rec.get("url", ""), freeze, recheck=True)

        with patch(RETENTION_BASE_QUERY_VARIANT_PATCH_PATH, side_effect=lambda team: _use_dwh_var.get()):
            kept, resolved, counts = revalidate_mismatches(state.mismatches, state.counts, check)

        for rec in resolved:
            self.stdout.write(
                self.style.SUCCESS(f"  RESOLVED {rec['short_id']} (team {rec['team_id']}) — {rec['resolution']}")
            )
        if kept:
            self.stdout.write(self.style.ERROR(f"  {len(kept)} mismatch(es) still reproduce"))
        return dataclasses.replace(
            state,
            mismatches=kept,
            resolved_mismatches=state.resolved_mismatches + resolved,
            counts=counts,
        )

    def _handle_empty(
        self,
        options: dict[str, Any],
        state_file: Optional[str],
        scope: str,
        prev_state: Optional[ProgressState],
        cursor: Optional[int],
        journal_rows: list[Row],
        journal_file: Optional[str],
    ) -> None:
        """Nothing newly selected: the filters match nothing, the sweep ran off the end, or an
        interrupted run already journaled everything that was left."""
        if state_file:
            next_cursor = max((r.id for r in journal_rows), default=None)
            new_state = merge_progress_state(
                prev_state, journal_rows, next_cursor=next_cursor, complete=True, scope=scope
            )
            save_progress_state(state_file, stamp_progress_state(new_state))
            self._absorb_journal(journal_file)
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
        self,
        insights: list[Insight],
        base_url: str,
        freeze: bool,
        recheck: bool,
        concurrency_opt: int,
        journal: Optional[LineSink] = None,
        recovered: Sequence[Row] = (),
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

        total = len(insights) + len(recovered)
        progress_lock = threading.Lock()
        # Recovered rows pre-seed the position and status totals so [done/total] tracks the whole
        # sweep rather than restarting at zero on resume; fresh_done feeds the ETA separately,
        # because the recovered rows cost this run nothing and would collapse the rate.
        done = len(recovered)
        fresh_done = 0
        counts: Counter[str] = Counter(row.status for row in recovered)
        started_at = perf_counter()

        def report(row: Row) -> None:
            nonlocal done, fresh_done
            with progress_lock:
                if journal is not None:
                    # Persist before printing: a local journal flushes every row to disk, the
                    # object-storage one uploads on its cadence and on SIGTERM, so an interrupt
                    # loses at most the in-flight window.
                    journal.append(journal_line(row))
                done += 1
                fresh_done += 1
                counts[row.status] += 1
                self._print_progress(done, total, row)
                self._print_heartbeat(done, total, fresh_done, started_at, counts)

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

    def _select_insights(
        self, options: dict[str, Any], after_id: Optional[int] = None, exclude_ids: Optional[set[int]] = None
    ) -> list[Insight]:
        queryset = Insight.objects.filter(saved=True, deleted=False, query__source__kind="RetentionQuery")
        if options["team_id"]:
            queryset = queryset.filter(team_id__in=options["team_id"])
        if options["insight_id"]:
            queryset = queryset.filter(id__in=options["insight_id"])
        if options["short_id"]:
            queryset = queryset.filter(short_id__in=options["short_id"])
        if exclude_ids:
            queryset = queryset.exclude(id__in=exclude_ids)
        queryset = queryset.select_related("team")
        if options["sample"]:
            return list(queryset.order_by("?")[: options["sample"]])
        # Keyset pagination: ascending id is a stable, unique sweep order and the cursor is just the last id.
        if after_id is not None:
            queryset = queryset.filter(id__gt=after_id)
        queryset = queryset.order_by("id")
        if options["all"]:
            return list(queryset)
        return list(queryset[: options["limit"]])

    def _print_progress(self, done: int, total: int, row: Row) -> None:
        if row.status == "OK":
            return  # keep the stream quiet; only surface the interesting outcomes
        is_bad = row.status == "MISMATCH" or row.status.startswith("ERROR")
        style = self.style.ERROR if is_bad else self.style.WARNING
        suffix = f" — {row.detail}" if row.detail else ""
        self.stdout.write(style(f"[{done}/{total}] {row.status} {row.short_id} (team {row.team_id}){suffix}"))

    def _print_heartbeat(self, done: int, total: int, fresh_done: int, started_at: float, counts: Counter[str]) -> None:
        """Elapsed/ETA line every HEARTBEAT_EVERY insights: per-row output stays quiet on OK, so a
        long healthy run would otherwise print nothing. Called with the progress lock held."""
        if done != total and done % HEARTBEAT_EVERY:
            return
        elapsed = perf_counter() - started_at
        eta = (elapsed / fresh_done) * (total - done)
        errors = sum(count for status, count in counts.items() if status.startswith("ERROR"))
        self.stdout.write(
            f"[{done}/{total}] elapsed={_fmt_duration(elapsed)} eta={_fmt_duration(eta)} — "
            f"ok={counts['OK']} mismatch={counts['MISMATCH']} errors={errors} skipped={counts['SKIPPED']}"
        )

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

    def _print_next_cursor(self, next_cursor: int, exhausted: bool) -> None:
        self.stdout.write("")
        if exhausted:
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
        self._print_record_list(
            "Resolved mismatches (stopped reproducing)", state.resolved_mismatches, self.style.SUCCESS
        )
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
            resolution = f" → {rec['resolution']}" if rec.get("resolution") else ""
            self.stdout.write(
                style(f"  {label}{rec['short_id']} (team {rec['team_id']}) {rec['url']}{detail}{resolution}")
            )
        if len(records) > cap:
            self.stdout.write(style(f"  …and {len(records) - cap} more (see state file)"))
