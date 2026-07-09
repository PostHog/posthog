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

_VERDICT_ORDER = {VERDICT_FAIL: 0, VERDICT_WARMUP: 1, VERDICT_PASS: 2, VERDICT_SKIP: 3}


def _sorted_rows(rows: Sequence[CohortComparison]) -> list[CohortComparison]:
    return sorted(rows, key=lambda r: (_VERDICT_ORDER.get(r.verdict, 9), -r.residual_pct, r.cohort_id))


def format_table(rows: Sequence[CohortComparison]) -> str:
    header = (
        f"{'cohort':<32} {'class':<24} {'old':>9} {'new':>9} {'both':>9} "
        f"{'only_old':>9} {'only_new':>9} {'raw%':>7} {'fresh':>8} {'warmup':>8} {'resid%':>7} {'verdict':>7}"
    )
    lines = [header, "-" * len(header)]
    for r in _sorted_rows(rows):
        label = f"{r.cohort_id} {r.name}"
        if len(label) > 31:
            label = label[:28] + "..."
        lines.append(
            f"{label:<32} {r.eligibility:<24} {r.old_count:>9} {r.new_count:>9} {r.both:>9} "
            f"{r.only_old:>9} {r.only_new:>9} {r.raw_diff_pct:>6.2f}% {r.fresh:>8} {r.warmup:>8} "
            f"{r.residual_pct:>6.2f}% {r.verdict:>7}"
        )
    return "\n".join(lines)


def format_notes(rows: Sequence[CohortComparison]) -> str:
    lines = []
    for r in _sorted_rows(rows):
        for note in r.notes:
            lines.append(f"  cohort {r.cohort_id}: {note}")
    return "\n".join(lines)


def format_summary(summary: AggregateSummary) -> str:
    lines = [
        f"verdicts: {summary.passed} PASS, {summary.failed} FAIL, {summary.warming_up} WARMUP, {summary.skipped} SKIP",
        f"skew explained: fresh={summary.fresh_total} warmup={summary.warmup_total} "
        f"residual={summary.residual_total} (of {summary.raw_diff_total} raw diff)",
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
