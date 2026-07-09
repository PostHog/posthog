"""Per-cohort divergence classification: R-EXCLUDE / R-FRESH / R-WARMUP / residual gate.

Pure — the sampled event-activity check is injected as a callable so tests need no
ClickHouse. Rules apply in order; each explains (removes) part of the raw diff, and
whatever remains is the gated residual.
"""

from __future__ import annotations

import heapq
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

from products.cohorts.backend.parity.eligibility import ScreenedCohort
from products.cohorts.backend.parity.fold import MembershipRecord, members

VERDICT_PASS = "PASS"
VERDICT_FAIL = "FAIL"
VERDICT_SKIP = "SKIP"
VERDICT_WARMUP = "WARMUP"  # reported, not gated: window exceeds pipeline age

# Persons (a sample of them) that had any event at/after the cutoff — the visibility
# probe for R-WARMUP: a person with no post-cutoff event was never (re)evaluated by the
# stream processor, so their absence on the new side is expected, not a bug.
ActivityProbe = Callable[[Sequence[str], datetime], set[str]]


@dataclass(frozen=True)
class CohortComparison:
    cohort_id: int
    name: str
    eligibility: str
    old_count: int = 0
    new_count: int = 0
    both: int = 0
    only_old: int = 0
    only_new: int = 0
    raw_diff_pct: float = 0.0
    fresh: int = 0
    warmup: int = 0
    residual_old: int = 0
    residual_new: int = 0
    residual_pct: float = 0.0
    verdict: str = VERDICT_SKIP
    notes: tuple[str, ...] = ()

    @property
    def gated(self) -> bool:
        return self.verdict in (VERDICT_PASS, VERDICT_FAIL)


@dataclass
class ClassifierConfig:
    since: datetime
    now: datetime
    threshold_pct: float = 0.5
    warmup_sample: int = 5000
    classify: bool = True  # False → raw diff only (--no-classify)
    activity_probe: Optional[ActivityProbe] = None

    @property
    def pipeline_age_days(self) -> float:
        return max((self.now - self.since).total_seconds() / 86_400, 0.0)


def _pct(part: int, whole: int) -> float:
    return part / whole * 100.0 if whole else 0.0


def classify_cohort(
    *,
    screened: ScreenedCohort,
    name: str,
    old_members: set[str],
    new_state: dict[str, MembershipRecord],
    last_realtime_calculation_at: Optional[datetime],
    config: ClassifierConfig,
) -> CohortComparison:
    if not screened.emits:
        return CohortComparison(
            cohort_id=screened.cohort_id,
            name=name,
            eligibility=screened.eligibility,
            verdict=VERDICT_SKIP,
            notes=("not emit-eligible: " + ", ".join(screened.drop_reasons or (screened.eligibility,)),),
        )

    new_members = members(new_state)
    both = old_members & new_members
    only_old = old_members - new_members
    only_new = new_members - old_members
    union_size = len(both) + len(only_old) + len(only_new)
    raw_pct = _pct(len(only_old) + len(only_new), union_size)
    notes: list[str] = []

    fresh = 0
    warmup = 0
    cohort_warmup = False
    if config.classify:
        # R-FRESH: new-side entries the old pipeline hasn't recomputed past yet.
        if last_realtime_calculation_at is None:
            fresh = len(only_new)
            if fresh:
                notes.append("old side never recomputed this cohort; all only_new counted fresh")
        else:
            fresh = sum(1 for p in only_new if new_state[p].last_updated > last_realtime_calculation_at)

        # R-WARMUP, cohort-level fast path: the whole behavioral window predates the pipeline.
        window = screened.max_window_days
        if window is not None and window > config.pipeline_age_days:
            cohort_warmup = True
            warmup = len(only_old)
            notes.append(f"window {window:g}d > pipeline age {config.pipeline_age_days:.1f}d — whole cohort warming up")
        elif only_old and config.warmup_sample > 0 and config.activity_probe is not None:
            # R-WARMUP, person-level: only_old persons invisible to the stream (no event
            # since the discovery cutoff) are expected skew. Sampled; extrapolated.
            cutoff = config.since if window is None else max(config.since, config.now - timedelta(days=window))
            sample = heapq.nsmallest(config.warmup_sample, only_old)
            active = config.activity_probe(sample, cutoff)
            sample_warmup = sum(1 for p in sample if p not in active)
            warmup = round(sample_warmup / len(sample) * len(only_old))
            if len(sample) < len(only_old):
                notes.append(f"warmup extrapolated from sample {len(sample)}/{len(only_old)}")

    residual_old = max(len(only_old) - warmup, 0)
    residual_new = max(len(only_new) - fresh, 0)
    residual_pct = _pct(residual_old + residual_new, union_size)

    # A warming cohort's only_old is fully attributed to warmup, but its residual (all
    # only_new there) is unexplained over-inclusion and must still gate — otherwise the
    # WARMUP verdict masks new-pipeline bugs exactly while parity testing matters most.
    if cohort_warmup and residual_pct <= config.threshold_pct:
        verdict = VERDICT_WARMUP
    elif residual_pct <= config.threshold_pct:
        verdict = VERDICT_PASS
    else:
        verdict = VERDICT_FAIL

    return CohortComparison(
        cohort_id=screened.cohort_id,
        name=name,
        eligibility=screened.eligibility,
        old_count=len(old_members),
        new_count=len(new_members),
        both=len(both),
        only_old=len(only_old),
        only_new=len(only_new),
        raw_diff_pct=raw_pct,
        fresh=fresh,
        warmup=warmup,
        residual_old=residual_old,
        residual_new=residual_new,
        residual_pct=residual_pct,
        verdict=verdict,
        notes=tuple(notes),
    )


@dataclass
class AggregateSummary:
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    warming_up: int = 0
    fresh_total: int = 0
    warmup_total: int = 0
    residual_total: int = 0
    raw_diff_total: int = 0
    pipeline_age_days: float = 0.0
    warnings: list[str] = field(default_factory=list)


def summarize(rows: Sequence[CohortComparison], *, config: ClassifierConfig) -> AggregateSummary:
    summary = AggregateSummary(pipeline_age_days=config.pipeline_age_days)
    for row in rows:
        if row.verdict == VERDICT_PASS:
            summary.passed += 1
        elif row.verdict == VERDICT_FAIL:
            summary.failed += 1
        elif row.verdict == VERDICT_WARMUP:
            summary.warming_up += 1
        else:
            summary.skipped += 1
        summary.fresh_total += row.fresh
        summary.warmup_total += row.warmup
        summary.residual_total += row.residual_old + row.residual_new
        summary.raw_diff_total += row.only_old + row.only_new
    return summary
