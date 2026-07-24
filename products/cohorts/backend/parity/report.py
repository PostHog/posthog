"""Render classified parity rows as a fixed-width table or a JSON document."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict
from typing import Any

from products.cohorts.backend.parity.classifier import (
    VERDICT_FAIL,
    VERDICT_PASS,
    VERDICT_SKIP,
    VERDICT_WARMUP,
    AggregateSummary,
    CohortComparison,
)
from products.cohorts.backend.parity.fold import ReconcileRunCompleteness
from products.cohorts.backend.parity.recompute import RecomputeComparison, RecomputeSummary

_VERDICT_ORDER = {VERDICT_FAIL: 0, VERDICT_WARMUP: 1, VERDICT_PASS: 2, VERDICT_SKIP: 3}
_RECOMPUTE_VERDICT_ORDER = {VERDICT_FAIL: 0, VERDICT_PASS: 1, VERDICT_SKIP: 2}


def _sorted_rows(rows: Sequence[CohortComparison]) -> list[CohortComparison]:
    return sorted(rows, key=lambda r: (_VERDICT_ORDER.get(r.verdict, 9), -r.residual_pct, r.cohort_id))


def format_table(rows: Sequence[CohortComparison]) -> str:
    header = (
        f"{'cohort':<32} {'class':<24} {'old':>9} {'obs':>9} {'new':>9} {'both':>9} "
        f"{'only_old':>9} {'only_new':>9} {'fresh':>7} {'stale':>7} {'resid%':>7} "
        f"{'unobs':>9} {'suspect':>8} {'verdict':>7}"
    )
    lines = [header, "-" * len(header)]
    for r in _sorted_rows(rows):
        label = f"{r.cohort_id} {r.name}"
        if len(label) > 31:
            label = label[:28] + "..."
        lines.append(
            f"{label:<32} {r.eligibility:<24} {r.old_count:>9} {r.observed:>9} {r.new_count:>9} {r.both:>9} "
            f"{r.only_old:>9} {r.only_new:>9} {r.fresh:>7} {r.stale:>7} {r.residual_pct:>6.2f}% "
            f"{r.unobserved:>9} {r.suspect_missing:>8} {r.verdict:>7}"
        )
    return "\n".join(lines)


def format_notes(rows: Sequence[CohortComparison]) -> str:
    lines = []
    for r in _sorted_rows(rows):
        for note in r.notes:
            lines.append(f"  cohort {r.cohort_id}: {note}")
    return "\n".join(lines)


def format_reconcile_notes(completeness: Sequence[ReconcileRunCompleteness]) -> tuple[str, ...]:
    notes: list[str] = []
    for run in sorted(completeness, key=lambda item: (item.run_id, item.cohort_id)):
        partition_summary = (
            f"{run.partitions_seen}/{run.expected_partitions}"
            if run.complete
            else f"partial {run.partitions_seen}/{run.expected_partitions}"
        )
        notes.append(f"reconcile run {run.run_id}: {partition_summary}")
    return tuple(notes)


def format_summary(summary: AggregateSummary) -> str:
    lines = [
        f"verdicts: {summary.passed} PASS, {summary.failed} FAIL, {summary.warming_up} WARMUP, {summary.skipped} SKIP",
        f"skew explained: fresh={summary.fresh_total} stale={summary.stale_total} dormant={summary.dormant_total} "
        f"(of {summary.raw_diff_total} raw diff); suspect_missing={summary.suspect_total}",
        f"pipeline age: {summary.pipeline_age_days:.1f}d since --since",
    ]
    for warning in summary.warnings:
        lines.append(f"WARNING: {warning}")
    return "\n".join(lines)


def to_json(
    rows: Sequence[CohortComparison],
    summary: AggregateSummary,
    meta: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "meta": dict(meta),
        "summary": asdict(summary),
        "cohorts": [asdict(r) for r in _sorted_rows(rows)],
    }


def _sorted_recompute_rows(rows: Sequence[RecomputeComparison]) -> list[RecomputeComparison]:
    return sorted(rows, key=lambda r: (_RECOMPUTE_VERDICT_ORDER.get(r.verdict, 9), -r.false_hard, r.cohort_id))


_RECOMPUTE_LABEL_WIDTH = 32
_RECOMPUTE_VERDICT_WIDTH = 7
_RECOMPUTE_HEADER = (
    f"{'cohort':<{_RECOMPUTE_LABEL_WIDTH}} {'fold':>8} {'oracle':>8} {'both':>8} {'false':>7} {'hard':>6} "
    f"{'evict':>6} {'miss':>7} {'grace':>6} {'seed':>6} {'bdry':>6} {'unseed':>6} {'post':>6} "
    f"{'verdict':>{_RECOMPUTE_VERDICT_WIDTH}}"
)
# A screen-skipped row spends every numeric column on the reason, so the line still aligns.
_RECOMPUTE_SKIP_WIDTH = len(_RECOMPUTE_HEADER) - _RECOMPUTE_LABEL_WIDTH - _RECOMPUTE_VERDICT_WIDTH - 2


def format_recompute_table(rows: Sequence[RecomputeComparison]) -> str:
    lines = [_RECOMPUTE_HEADER, "-" * len(_RECOMPUTE_HEADER)]
    for r in _sorted_recompute_rows(rows):
        label = f"{r.cohort_id} {r.name}"
        if len(label) > _RECOMPUTE_LABEL_WIDTH - 1:
            label = label[: _RECOMPUTE_LABEL_WIDTH - 4] + "..."
        if not r.supported:
            reason = f"SKIP: {r.skip_reason}"[:_RECOMPUTE_SKIP_WIDTH]
            lines.append(
                f"{label:<{_RECOMPUTE_LABEL_WIDTH}} {reason:<{_RECOMPUTE_SKIP_WIDTH}} "
                f"{r.verdict:>{_RECOMPUTE_VERDICT_WIDTH}}"
            )
            continue
        lines.append(
            f"{label:<{_RECOMPUTE_LABEL_WIDTH}} {r.fold_count:>8} {r.oracle_count:>8} {r.both:>8} "
            f"{r.false_members:>7} {r.false_hard:>6} {r.eviction_pending:>6} {r.missing:>7} {r.missing_grace:>6} "
            f"{r.missing_seed_domain:>6} {r.missing_boundary_day:>6} {r.missing_unseeded_day:>6} "
            f"{r.missing_post_boundary:>6} {r.verdict:>{_RECOMPUTE_VERDICT_WIDTH}}"
        )
    return "\n".join(lines)


def format_recompute_notes(rows: Sequence[RecomputeComparison]) -> str:
    lines = []
    for r in _sorted_recompute_rows(rows):
        for run in sorted(r.reconcile_runs, key=lambda item: item.run_id):
            state = (
                f"{run.partitions_seen}/{run.expected_partitions}"
                if run.complete
                else (f"partial {run.partitions_seen}/{run.expected_partitions}")
            )
            lines.append(f"  cohort {r.cohort_id}: reconcile run {run.run_id}: {state}")
        for note in r.notes:
            lines.append(f"  cohort {r.cohort_id}: {note}")
        if r.expires_by_day:
            summary = ", ".join(f"{day}: {count}" for day, count in r.expires_by_day.items())
            lines.append(f"  cohort {r.cohort_id}: boundary-day gap expires — {summary}")
    return "\n".join(lines)


def format_recompute_summary(summary: RecomputeSummary) -> str:
    lines = [
        f"verdicts: {summary.passed} PASS, {summary.failed} FAIL, {summary.skipped} SKIP",
        f"over-count: false_hard={summary.false_hard_total} (eviction_pending={summary.eviction_pending_total}); "
        f"under-count: missing={summary.missing_total} (seed_domain={summary.seed_domain_total}, "
        f"unseeded={summary.unseeded_total}, post_boundary={summary.post_boundary_total}, "
        f"boundary={summary.boundary_total}, unsegmented={summary.unsegmented_total})",
    ]
    for warning in summary.warnings:
        lines.append(f"WARNING: {warning}")
    return "\n".join(lines)


def to_recompute_json(
    rows: Sequence[RecomputeComparison],
    summary: RecomputeSummary,
    meta: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "meta": dict(meta),
        "summary": asdict(summary),
        "cohorts": [asdict(r) for r in _sorted_recompute_rows(rows)],
    }
