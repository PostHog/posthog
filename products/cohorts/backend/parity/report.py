"""Render parity rows as a fixed-width table or a JSON document."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, fields
from typing import Any

from products.cohorts.backend.parity.population import PopulationComparison, PopulationSummary
from products.cohorts.backend.parity.recompute import (
    VERDICT_FAIL,
    VERDICT_PASS,
    VERDICT_SKIP,
    RecomputeComparison,
    RecomputeSummary,
)

_RECOMPUTE_VERDICT_ORDER = {VERDICT_FAIL: 0, VERDICT_PASS: 1, VERDICT_SKIP: 2}


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
        f"boundary={summary.boundary_total}, unsegmented={summary.unsegmented_total}, "
        f"unattributed={summary.unattributed_total})",
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


def _sorted_population_rows(rows: Sequence[PopulationComparison]) -> list[PopulationComparison]:
    # Worst agreement first, because with no verdict to sort on that is what a report-only mode is
    # read for. Skipped rows have no match_pct and sort last on the compared key alone.
    return sorted(rows, key=lambda r: (not r.compared, r.match_pct if r.match_pct is not None else 0.0, r.cohort_id))


_POPULATION_LABEL_WIDTH = 32
_POPULATION_MATCH_WIDTH = 7
_POPULATION_HEADER = (
    f"{'cohort':<{_POPULATION_LABEL_WIDTH}} {'fold':>9} {'legacy':>9} {'both':>9} "
    f"{'only_fold':>9} {'only_legacy':>11} {'match%':>{_POPULATION_MATCH_WIDTH}}"
)
# A skipped row spends every count column on the reason, so the line still aligns.
_POPULATION_SKIP_WIDTH = len(_POPULATION_HEADER) - _POPULATION_LABEL_WIDTH - _POPULATION_MATCH_WIDTH - 2


def format_population_table(rows: Sequence[PopulationComparison]) -> str:
    lines = [_POPULATION_HEADER, "-" * len(_POPULATION_HEADER)]
    for r in _sorted_population_rows(rows):
        label = f"{r.cohort_id} {r.name}"
        if len(label) > _POPULATION_LABEL_WIDTH - 1:
            label = label[: _POPULATION_LABEL_WIDTH - 4] + "..."
        if not r.compared:
            reason = f"SKIP: {r.skip_reason}"[:_POPULATION_SKIP_WIDTH]
            lines.append(
                f"{label:<{_POPULATION_LABEL_WIDTH}} {reason:<{_POPULATION_SKIP_WIDTH}} "
                f"{'-':>{_POPULATION_MATCH_WIDTH}}"
            )
            continue
        match = "-" if r.match_pct is None else f"{r.match_pct:.2f}%"
        lines.append(
            f"{label:<{_POPULATION_LABEL_WIDTH}} {r.fold_count:>9} {r.legacy_count:>9} {r.both:>9} "
            f"{r.only_fold:>9} {r.only_legacy:>11} {match:>{_POPULATION_MATCH_WIDTH}}"
        )
    return "\n".join(lines)


def format_population_summary(summary: PopulationSummary) -> str:
    # match_pct is None when nothing was compared: no data, not total agreement.
    match = f"{summary.match_pct:.2f}%" if summary.match_pct is not None else "-"
    lines = [
        f"compared: {summary.compared}, skipped: {summary.skipped}",
        f"fold={summary.fold_total} legacy={summary.legacy_total} both={summary.both_total} "
        f"only_fold={summary.only_fold_total} only_legacy={summary.only_legacy_total}; match={match}",
    ]
    for warning in summary.warnings:
        lines.append(f"WARNING: {warning}")
    return "\n".join(lines)


def to_population_json(
    rows: Sequence[PopulationComparison],
    summary: PopulationSummary,
    meta: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "meta": dict(meta),
        "summary": asdict(summary),
        # Not asdict: it deep-copies containers, and with --with-ids the id tuples can hold the
        # whole diff; a shallow dict keeps them shared with the rows. No nested dataclasses here.
        "cohorts": [{f.name: getattr(r, f.name) for f in fields(r)} for r in _sorted_population_rows(rows)],
    }
