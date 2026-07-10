"""Per-cohort divergence classification: O-bounded diff + missed-emission signal.

The membership diff is bounded to the observed universe O = persons the new pipeline
emitted a decision for since the store wipe (fold.py:observed). Within O both pipelines
have weighed in, so the diff is sound; each rule explains (removes) part of it and the
remainder is the gated residual:

- R-EXCLUDE: persons in `old - O` are excluded from the diff entirely (the new pipeline
  never evaluated them — flip-only emission means a never-member emits nothing).
- R-FRESH:  `only_new` entries whose flip is newer than the old side's last recompute —
  the old pipeline simply hasn't caught up yet (expected, not over-inclusion).
- R-STALE:  the mirror on `only_old` — the new pipeline already flipped a person to
  `left` but the old side hasn't recomputed past that eviction, so it still says entered.

R-EXCLUDE hides real under-inclusion bugs (a processor that emits nothing would pass an
O-bounded gate), so a separate *missed-emission* signal probes `old - O` for recent
activity: `suspect_missing` persons (active since the discovery cutoff yet undecided by
the new pipeline) gate FAIL where the store provably covers the window, and are reported
(WARMUP, not gated) where the window predates the pipeline. The inactive remainder is
`dormant` (expected).

Pure — the sampled event-activity probe is injected as a callable so tests need no
ClickHouse.
"""

from __future__ import annotations

import math
import heapq
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

from products.cohorts.backend.parity.eligibility import ScreenedCohort
from products.cohorts.backend.parity.fold import MembershipRecord, members, observed

VERDICT_PASS = "PASS"
VERDICT_FAIL = "FAIL"
VERDICT_SKIP = "SKIP"
VERDICT_WARMUP = "WARMUP"  # reported, not gated: unobserved actives on a window > pipeline age

# Persons (a sample of them) that had any event at/after the cutoff — the missed-emission
# probe over `old - O`: a person with no post-cutoff event was never (re)evaluated by the
# stream processor, so their absence on the new side is expected (dormant), not a bug.
ActivityProbe = Callable[[Sequence[str], datetime], set[str]]


@dataclass(frozen=True)
class CohortComparison:
    cohort_id: int
    name: str
    eligibility: str
    old_count: int = 0  # full converged old snapshot (superset of the observed universe)
    observed: int = 0  # |O| — persons the new pipeline decided on
    new_count: int = 0  # entered set within O
    both: int = 0
    only_old: int = 0  # (old ∩ O) - new_members
    only_new: int = 0
    raw_diff_pct: float = 0.0  # over the observed union
    fresh: int = 0
    stale: int = 0
    residual_old: int = 0
    residual_new: int = 0
    residual_pct: float = 0.0
    unobserved: int = 0  # old - O, excluded from the diff, split by the probe below
    suspect_missing: int = 0  # unobserved but recently active — likely under-inclusion
    dormant: int = 0  # unobserved and inactive — expected
    suspect_pct: float = 0.0
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
    classify: bool = True  # False → O-bounded raw diff only (--no-classify)
    activity_probe: Optional[ActivityProbe] = None

    @property
    def pipeline_age_days(self) -> float:
        return max((self.now - self.since).total_seconds() / 86_400, 0.0)


def _pct(part: int, whole: int) -> float:
    return part / whole * 100.0 if whole else 0.0


def _probe_cutoff(window: Optional[float], since: datetime, now: datetime) -> datetime:
    """`since` if no window, else `max(since, now - window)`.

    A window reaching at/before `since` (including inf and huge finite windows that would
    overflow `timedelta`) clamps to `since` — the earliest a qualifying event can be.
    """
    if window is None:
        return since
    pipeline_age_days = (now - since).total_seconds() / 86_400
    if math.isinf(window) or window >= pipeline_age_days:
        return since
    return now - timedelta(days=window)


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

    obs = observed(new_state)
    new_members = members(new_state)
    both = old_members & new_members
    only_old = (old_members & obs) - new_members  # both weighed in; new landed `left`
    only_new = new_members - old_members
    unobserved = old_members - obs  # excluded from the diff (R-EXCLUDE)
    union_size = len(both) + len(only_old) + len(only_new)
    raw_pct = _pct(len(only_old) + len(only_new), union_size)
    notes: list[str] = []

    fresh = 0
    stale = 0
    suspect_missing = 0
    if config.classify:
        # R-FRESH / R-STALE: entries whose flip is newer than the old side's last recompute.
        if last_realtime_calculation_at is None:
            fresh = len(only_new)
            # stale stays 0: a never-recomputed old side has no entered rows to be stale.
            if fresh:
                notes.append("old side never recomputed this cohort; all only_new counted fresh")
        else:
            fresh = sum(1 for p in only_new if new_state[p].last_updated > last_realtime_calculation_at)
            stale = sum(1 for p in only_old if new_state[p].last_updated > last_realtime_calculation_at)

        window = screened.max_window_days
        if unobserved and config.warmup_sample > 0 and config.activity_probe is not None:
            # Missed-emission probe: `old - O` persons active since the discovery cutoff were
            # evaluable by the stream but never emitted — likely under-inclusion. Sampled,
            # extrapolated. The inactive remainder is dormant (expected R-EXCLUDE skew).
            cutoff = _probe_cutoff(window, config.since, config.now)
            sample = heapq.nsmallest(config.warmup_sample, unobserved)
            active = config.activity_probe(sample, cutoff)
            sample_suspect = sum(1 for p in sample if p in active)
            suspect_missing = round(sample_suspect / len(sample) * len(unobserved))
            if len(sample) < len(unobserved):
                notes.append(f"suspect_missing extrapolated from sample {len(sample)}/{len(unobserved)}")
            if window == 0:
                notes.append("minute/hour window: probe cutoff is now, suspect≈0 by construction")
        elif unobserved and config.warmup_sample <= 0:
            notes.append("suspect check skipped (--warmup-sample 0); unobserved population unprobed")

    residual_old = max(len(only_old) - stale, 0)
    residual_new = max(len(only_new) - fresh, 0)
    residual_pct = _pct(residual_old + residual_new, union_size)
    dormant = max(len(unobserved) - suspect_missing, 0)
    # Silent-miss share of the whole membership (full union, not O-bounded).
    suspect_pct = _pct(suspect_missing, len(old_members) + len(only_new))

    # The store provably covers the behavioral window (or there is none), so an unobserved
    # active is a real miss, not a pre-`since` qualifier the snapshot cannot resolve.
    sound = screened.max_window_days is None or screened.max_window_days <= config.pipeline_age_days

    if residual_pct > config.threshold_pct:
        verdict = VERDICT_FAIL
    elif suspect_pct > config.threshold_pct:
        verdict = VERDICT_FAIL if sound else VERDICT_WARMUP
    else:
        verdict = VERDICT_PASS

    return CohortComparison(
        cohort_id=screened.cohort_id,
        name=name,
        eligibility=screened.eligibility,
        old_count=len(old_members),
        observed=len(obs),
        new_count=len(new_members),
        both=len(both),
        only_old=len(only_old),
        only_new=len(only_new),
        raw_diff_pct=raw_pct,
        fresh=fresh,
        stale=stale,
        residual_old=residual_old,
        residual_new=residual_new,
        residual_pct=residual_pct,
        unobserved=len(unobserved),
        suspect_missing=suspect_missing,
        dormant=dormant,
        suspect_pct=suspect_pct,
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
    stale_total: int = 0
    suspect_total: int = 0
    dormant_total: int = 0
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
        summary.stale_total += row.stale
        summary.suspect_total += row.suspect_missing
        summary.dormant_total += row.dormant
        summary.residual_total += row.residual_old + row.residual_new
        summary.raw_diff_total += row.only_old + row.only_new + row.unobserved
    return summary
