"""Turn ClickHouse's plans and the thresholds into findings and the two granule shares.

Everything here is pure: no ClickHouse, no Redis, no Celery. The job hands over the outer query's
plan, one plan per stubbed ``IN`` subquery, and the two denominator granule counts from 16.6; this
module reads the findings and the shares off them.
"""

from posthog.schema import QueryScanWarning

from posthog.dataclasses import frozen
from posthog.query_scan.explain import PlanTableRead, QueryPlan
from posthog.query_scan.findings import (
    FindingKind,
    FindingReason,
    ScanMeasurements,
    ScanThresholds,
    build_warning,
    explain_evidence,
)

__all__ = ["PlanSet", "QueryScanResult", "analyze"]

# The kind the runner reports for a raw HogQL query. Any other kind is an insight built from
# pickers; the same rules apply, only the finding copy differs.
_SQL_QUERY_KIND = "HogQLQuery"


@frozen
class PlanSet:
    """The plans one job produced, plus the denominators for the granule shares (16.6).

    ``team_granules`` and ``range_granules`` are the selected granules of the two denominator
    ``EXPLAIN``s the job ran: the team's whole data, and the team's data over the query's range.
    """

    outer: QueryPlan | None
    subqueries: tuple[QueryPlan, ...] = ()
    team_granules: int | None = None
    range_granules: int | None = None


@frozen(eq=False)
class QueryScanResult:
    findings: list[QueryScanWarning]
    explain_ok: bool
    reads_events: bool = False
    range_share: float | None = None
    project_share: float | None = None

    def finding_kinds(self) -> list[str]:
        return [str(finding.kind) for finding in self.findings]


def analyze(
    plans: PlanSet,
    thresholds: ScanThresholds,
    *,
    query_kind: str,
    open_filters_placeholder: bool,
    measurements: ScanMeasurements,
) -> QueryScanResult:
    """`open_filters_placeholder` is true when the query left its date range to a `{filters}`
    placeholder that expanded to no bound, so the fix is on the insight, not in the SQL."""
    if plans.outer is None:
        return QueryScanResult(findings=[], explain_ok=False)

    outer_events = plans.outer.events_read()
    numerator = outer_events.selected_granules() if outer_events is not None else None
    range_share = _share(numerator, plans.range_granules)
    project_share = _share(numerator, plans.team_granules)

    findings: list[QueryScanWarning] = []
    # The outer plan's events read is the one the range share measures, so its no-event-filter gate
    # can use the share. A subquery has no share of its own, so it gates on the skip-step fallback.
    findings += _findings_for_plan(
        plans.outer,
        thresholds,
        measurements,
        query_kind=query_kind,
        open_filters_placeholder=open_filters_placeholder,
        range_share=range_share,
        subquery_index=None,
    )
    for index, subquery in enumerate(plans.subqueries):
        findings += _findings_for_plan(
            subquery,
            thresholds,
            measurements,
            query_kind=query_kind,
            open_filters_placeholder=open_filters_placeholder,
            range_share=None,
            subquery_index=index,
        )

    return QueryScanResult(
        findings=findings,
        explain_ok=True,
        reads_events=outer_events is not None,
        range_share=range_share,
        project_share=project_share,
    )


def _findings_for_plan(
    plan: QueryPlan,
    thresholds: ScanThresholds,
    measurements: ScanMeasurements,
    *,
    query_kind: str,
    open_filters_placeholder: bool,
    range_share: float | None,
    subquery_index: int | None,
) -> list[QueryScanWarning]:
    events_read = plan.events_read()
    # A plan that does not read the events table has no denominator and nothing to advise on.
    if events_read is None:
        return []

    findings: list[QueryScanWarning] = []

    if not events_read.has_timestamp_key():
        reason = FindingReason.FILTERS if open_filters_placeholder and query_kind == _SQL_QUERY_KIND else None
        findings.append(
            build_warning(
                kind=FindingKind.NO_START_DATE,
                query_kind=query_kind,
                reason=reason,
                measurements=measurements,
                evidence=_min_max_evidence(events_read, subquery_index),
            )
        )

    if _event_key_missing(events_read) and _passes_event_gate(events_read, range_share, thresholds):
        findings.append(
            build_warning(
                kind=FindingKind.NO_EVENT_FILTER,
                query_kind=query_kind,
                measurements=measurements,
                evidence=_primary_key_evidence(events_read, subquery_index),
            )
        )

    person_read = _persons_join_read(plan, events_read, thresholds)
    if person_read is not None:
        findings.append(
            build_warning(
                kind=FindingKind.PERSONS_JOIN,
                query_kind=query_kind,
                measurements=measurements,
                evidence=_primary_key_evidence(person_read, subquery_index),
            )
        )

    return findings


def _event_key_missing(read: PlanTableRead) -> bool:
    primary_key = read.primary_key()
    return primary_key is None or "event" not in primary_key.keys


def _passes_event_gate(read: PlanTableRead, range_share: float | None, thresholds: ScanThresholds) -> bool:
    """The read is a large share of the range, so an event filter would have saved real work.

    With the range share known, the gate is that share against `event_ratio`. Without it (a
    subquery, or a failed denominator), fall back to whether any skip index already pruned most of
    the read, which means something else narrowed it and an event filter would not help much.
    """
    if range_share is not None:
        return range_share >= thresholds.event_ratio
    return not _any_skip_pruned_half(read)


def _any_skip_pruned_half(read: PlanTableRead) -> bool:
    for skip in read.skip_steps():
        if (
            skip.initial_granules is not None
            and skip.initial_granules > 0
            and skip.selected_granules is not None
            and skip.selected_granules < 0.5 * skip.initial_granules
        ):
            return True
    return False


def _persons_join_read(plan: QueryPlan, events_read: PlanTableRead, thresholds: ScanThresholds) -> PlanTableRead | None:
    events_granules = events_read.selected_granules()
    if events_granules is None:
        return None
    threshold = thresholds.persons_ratio * events_granules
    for read in plan.person_reads():
        selected = read.selected_granules()
        if selected is not None and selected >= threshold:
            return read
    return None


def _min_max_evidence(read: PlanTableRead, subquery_index: int | None) -> str:
    step = read.min_max()
    keys = step.keys if step is not None else ()
    before = step.initial_granules if step is not None else None
    after = step.selected_granules if step is not None else None
    return explain_evidence(keys, before=before, after=after, subquery_index=subquery_index)


def _primary_key_evidence(read: PlanTableRead, subquery_index: int | None) -> str:
    step = read.primary_key()
    keys = step.keys if step is not None else ()
    before = step.initial_granules if step is not None else None
    after = step.selected_granules if step is not None else None
    return explain_evidence(keys, before=before, after=after, subquery_index=subquery_index)


def _share(numerator: int | None, denominator: int | None) -> float | None:
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return min(1.0, max(0.0, numerator / denominator))
