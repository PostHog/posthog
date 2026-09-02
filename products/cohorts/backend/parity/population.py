"""Set diff of the folded shadow membership against the legacy batch cohort population.

The ``--oracle population`` mode compares two sets of person ids and nothing else: the fold's
current members, and the population the legacy batch calculation wrote to ClickHouse
``cohortpeople`` at the cohort's pinned version (the set the cohort page shows). No cohort filter is
read, so no shape can be unsupported and no evaluator is reimplemented — and equally, nothing here
attributes divergence to a side. Report-only: there is no verdict and no gate.

Pure — no Django, no ClickHouse, no Kafka.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass(frozen=True)
class PopulationComparison:
    cohort_id: int
    name: str
    compared: bool
    skip_reason: str = ""
    fold_count: int = 0
    legacy_count: int = 0
    both: int = 0
    only_fold: int = 0
    only_legacy: int = 0
    # None on skip rows: a skipped cohort has no agreement to report, and a 0.0 in the JSON would
    # read as total disagreement rather than as no data.
    match_pct: Optional[float] = None
    legacy_version: Optional[int] = None
    calculated_at: Optional[str] = None
    only_fold_ids: tuple[str, ...] = ()
    only_legacy_ids: tuple[str, ...] = ()


def _match_pct(both: int, union: int) -> float:
    # An empty union is total agreement, not a ZeroDivisionError: neither side has anyone.
    return 100.0 if union == 0 else both / union * 100


def compare_populations(
    *,
    cohort_id: int,
    name: str,
    fold_members: set[str],
    legacy_members: set[str],
    legacy_version: int,
    calculated_at: datetime,
    with_ids: bool,
) -> PopulationComparison:
    both = fold_members & legacy_members
    only_fold = fold_members - legacy_members
    only_legacy = legacy_members - fold_members
    return PopulationComparison(
        cohort_id=cohort_id,
        name=name,
        compared=True,
        fold_count=len(fold_members),
        legacy_count=len(legacy_members),
        both=len(both),
        only_fold=len(only_fold),
        only_legacy=len(only_legacy),
        match_pct=_match_pct(len(both), len(both) + len(only_fold) + len(only_legacy)),
        legacy_version=legacy_version,
        calculated_at=calculated_at.isoformat(),
        # Complete or absent: sampling a divergence list would make it unusable for the lookups
        # (`is this person in the seeder's output?`) the flag exists for.
        only_fold_ids=tuple(sorted(only_fold)) if with_ids else (),
        only_legacy_ids=tuple(sorted(only_legacy)) if with_ids else (),
    )


def skip_population(*, cohort_id: int, name: str, reason: str) -> PopulationComparison:
    """A cohort with no usable oracle. Counts stay zeroed so a skip cannot render as agreement."""
    return PopulationComparison(cohort_id=cohort_id, name=name, compared=False, skip_reason=reason)


@dataclass
class PopulationSummary:
    compared: int = 0
    skipped: int = 0
    fold_total: int = 0
    legacy_total: int = 0
    both_total: int = 0
    only_fold_total: int = 0
    only_legacy_total: int = 0
    # None when nothing was compared: an all-skip run must ship null, not a perfect 100.0.
    match_pct: Optional[float] = None
    warnings: list[str] = field(default_factory=list)


def summarize_population(rows: Sequence[PopulationComparison]) -> PopulationSummary:
    summary = PopulationSummary()
    for row in rows:
        if not row.compared:
            summary.skipped += 1
            continue
        summary.compared += 1
        summary.fold_total += row.fold_count
        summary.legacy_total += row.legacy_count
        summary.both_total += row.both
        summary.only_fold_total += row.only_fold
        summary.only_legacy_total += row.only_legacy
    if summary.compared:
        summary.match_pct = _match_pct(
            summary.both_total, summary.both_total + summary.only_fold_total + summary.only_legacy_total
        )
    return summary
