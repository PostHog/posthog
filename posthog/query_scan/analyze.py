"""Turn ClickHouse's plans into findings and the two shares.

Pure: no ClickHouse, Redis or Celery. A share is the outer read's granules over a denominator, the
project's events in the query's date range or over all time.
"""

from posthog.schema import QueryScanFindingKind, QueryScanFindingReason, QueryScanWarning

from posthog.dataclasses import frozen
from posthog.query_scan.event_filter import EventFilterOutcome
from posthog.query_scan.explain import PlanIndex, PlanTableRead, QueryPlan
from posthog.query_scan.findings import SQL_QUERY_KIND, build_warning, explain_evidence
from posthog.query_scan.flag import QueryScanFlag

__all__ = ["PlanSet", "QueryScanResult", "analyze"]


@frozen
class PlanSet:
    """The plans one job produced. ``team_granules`` and ``range_granules`` are the denominators:
    the project's events over all time, and over the query's date range.
    """

    outer: QueryPlan | None
    subqueries: tuple[QueryPlan, ...] = ()
    team_granules: int | None = None
    range_granules: int | None = None


@frozen(eq=False)
class QueryScanResult:
    findings: list[QueryScanWarning]
    explain_ok: bool
    range_share: float | None = None
    project_share: float | None = None

    def finding_kinds(self) -> list[str]:
        return [str(finding.kind) for finding in self.findings]


def analyze(
    plans: PlanSet,
    flag: QueryScanFlag,
    *,
    query_kind: str,
    open_filters_placeholder: bool,
    event_filter: EventFilterOutcome | None = None,
    table_row_averages: dict[str, float] | None = None,
    all_time: bool = False,
    all_history_by_design: bool = False,
) -> QueryScanResult:
    """`open_filters_placeholder` is true when the query left its date range to a `{filters}`
    placeholder that expanded to no bound, so the fix is on the insight, not in the SQL.

    `event_filter` is the combined tree-and-plan verdict for the outer execution, from the job.
    None means no verdict shipped, so the outer read's no-event-filter gate falls back to the
    plan's keys alone. A subquery is never classified from the tree, so it always uses that
    fallback.

    `table_row_averages` is empty when the `system.parts` read failed; the persons gate then falls
    back to a raw granule comparison, so the analysis still runs without the metadata query.

    `all_history_by_design` is true when the insight has to read from the project's first event
    whatever its date range, so no start date is reported: there is nothing the person can change.
    """
    averages = table_row_averages or {}
    if plans.outer is None:
        return QueryScanResult(findings=[], explain_ok=False)

    outer_events = plans.outer.heaviest_events_read()
    numerator = outer_events.selected_granules() if outer_events is not None else None
    range_share = _share(numerator, plans.range_granules)
    project_share = _share(numerator, plans.team_granules)

    findings: list[QueryScanWarning] = []
    # Only the outer read has a range share; a subquery gates on the skip-step fallback.
    findings += _findings_for_plan(
        plans.outer,
        flag,
        query_kind=query_kind,
        open_filters_placeholder=open_filters_placeholder,
        all_time=all_time,
        all_history_by_design=all_history_by_design,
        range_share=range_share,
        subquery_index=None,
        table_row_averages=averages,
        event_filter=event_filter,
    )
    for index, subquery in enumerate(plans.subqueries):
        findings += _findings_for_plan(
            subquery,
            flag,
            query_kind=query_kind,
            open_filters_placeholder=open_filters_placeholder,
            all_time=all_time,
            all_history_by_design=all_history_by_design,
            range_share=None,
            subquery_index=index,
            table_row_averages=averages,
            event_filter=None,
        )

    return QueryScanResult(
        findings=findings,
        explain_ok=True,
        range_share=range_share,
        project_share=project_share,
    )


def _findings_for_plan(
    plan: QueryPlan,
    flag: QueryScanFlag,
    *,
    query_kind: str,
    open_filters_placeholder: bool,
    all_time: bool,
    all_history_by_design: bool,
    range_share: float | None,
    subquery_index: int | None,
    table_row_averages: dict[str, float],
    event_filter: EventFilterOutcome | None,
) -> list[QueryScanWarning]:
    # A plan that reads the events table more than once is judged on its largest read, except that
    # any read with no start bound is enough for the start-date finding. A lighter read with no event
    # filter goes unmentioned even when it is nearly as large, because gating each read on its own
    # share would cost a denominator per read.
    heaviest = plan.heaviest_events_read()
    # A plan that does not read the events table has no denominator and nothing to advise on.
    if heaviest is None:
        return []

    findings: list[QueryScanWarning] = []

    # "All time" reaches the plan as a bound at the project's first event, so only the setting
    # says the person chose no start date; it applies to the outer query, not its subqueries.
    chose_all_time = all_time and subquery_index is None
    unbounded = next((read for read in plan.events_reads() if read.timestamp_bounds().lower is None), None)
    if (unbounded is not None or chose_all_time) and not all_history_by_design:
        reason = QueryScanFindingReason.FILTERS if open_filters_placeholder and query_kind == SQL_QUERY_KIND else None
        findings.append(
            build_warning(
                kind=QueryScanFindingKind.NO_START_DATE,
                query_kind=query_kind,
                reason=reason,
                evidence=(
                    "The date range is set to All time, so the query starts at the project's first event."
                    if chose_all_time
                    else _evidence((unbounded if unbounded is not None else heaviest).min_max(), subquery_index)
                ),
            )
        )

    no_event_filter, event_reason = _no_event_filter(heaviest, event_filter)
    if no_event_filter and _passes_event_gate(heaviest, range_share, flag.event_ratio):
        findings.append(
            build_warning(
                kind=QueryScanFindingKind.NO_EVENT_FILTER,
                query_kind=query_kind,
                reason=event_reason,
                evidence=_evidence(heaviest.primary_key(), subquery_index),
            )
        )

    person_read = _persons_join_read(plan, heaviest, flag.persons_ratio, table_row_averages)
    if person_read is not None:
        findings.append(
            build_warning(
                kind=QueryScanFindingKind.PERSONS_JOIN,
                query_kind=query_kind,
                evidence=_evidence(person_read.primary_key(), subquery_index),
            )
        )

    return findings


def _no_event_filter(
    heaviest: PlanTableRead, event_filter: EventFilterOutcome | None
) -> tuple[bool, QueryScanFindingReason | None]:
    """Whether the heaviest read has no usable event filter, and the reason for the copy. The tree's
    verdict carries the reason when the job shipped one; the read's keys alone name none.
    """
    if event_filter is not None:
        reason = QueryScanFindingReason(event_filter.reason) if event_filter.reason is not None else None
        return event_filter.classification != "usable", reason
    return not heaviest.uses_event_key(), None


def _passes_event_gate(read: PlanTableRead, range_share: float | None, event_ratio: float) -> bool:
    """With the range share known, gate on it. Without one (a subquery, or a failed denominator), a
    skip index that already pruned most of the read means an event filter would not help much.
    """
    if range_share is not None:
        return range_share >= event_ratio
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


def _persons_join_read(
    plan: QueryPlan,
    events_read: PlanTableRead,
    persons_ratio: float,
    table_row_averages: dict[str, float],
) -> PlanTableRead | None:
    events_granules = events_read.selected_granules()
    if events_granules is None:
        return None
    events_rows = _estimated_rows(events_read, events_granules, table_row_averages)
    for read in plan.person_reads():
        person_granules = read.selected_granules()
        if person_granules is None:
            continue
        person_rows = _estimated_rows(read, person_granules, table_row_averages)
        # A granule holds several times more rows in the persons tables than in events, so a raw
        # granule ratio under-fires the gate; scale each side to rows when both averages are known.
        if events_rows is not None and person_rows is not None:
            if person_rows >= persons_ratio * events_rows:
                return read
        elif person_granules >= persons_ratio * events_granules:
            return read
    return None


def _estimated_rows(read: PlanTableRead, granules: int, table_row_averages: dict[str, float]) -> float | None:
    average = read.average_rows_per_granule(table_row_averages)
    return granules * average if average is not None else None


def _evidence(step: PlanIndex | None, subquery_index: int | None) -> str:
    keys = step.keys if step is not None else ()
    before = step.initial_granules if step is not None else None
    after = step.selected_granules if step is not None else None
    return explain_evidence(keys, before=before, after=after, subquery_index=subquery_index)


def _share(numerator: int | None, denominator: int | None) -> float | None:
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return min(1.0, max(0.0, numerator / denominator))
