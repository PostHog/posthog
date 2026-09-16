"""Turn ClickHouse's plans into findings and the two shares.

Pure: no ClickHouse, Redis or Celery. A share is the outer read's granules over a denominator, the
project's events in the query's date range or over all time. The plan says what was read; the
facts the trigger read off the tree say why, which picks each finding's reason and with it its
wording and whether the person can act on it.
"""

from posthog.schema import QueryScanFindingKind, QueryScanFindingReason, QueryScanWarning

from posthog.dataclasses import frozen
from posthog.query_scan.event_filter import EventFilterOutcome
from posthog.query_scan.explain import PlanIndex, PlanTableRead, QueryPlan
from posthog.query_scan.findings import SQL_QUERY_KIND, build_warning, explain_evidence
from posthog.query_scan.flag import QueryScanFlag
from posthog.query_scan.tree_facts import TreeFacts

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


@frozen
class RunFacts:
    """What the trigger knew about the run that the plan cannot show.

    ``all_time`` and ``dashboard_all_time`` say a picker chose All time, and where. The by-design
    flags come from the insight's own settings: a first-time math has to read from the first event,
    and an active-user count on All events has to read every event. ``tree`` is what the prepared
    tree said about the events reads, or None when nothing shipped.
    """

    all_time: bool = False
    dashboard_all_time: bool = False
    all_history_by_design: bool = False
    all_events_by_design: bool = False
    open_filters_placeholder: bool = False
    tree: TreeFacts | None = None


@frozen(eq=False)
class QueryScanResult:
    findings: list[QueryScanWarning]
    explain_ok: bool
    range_share: float | None = None
    project_share: float | None = None

    def finding_kinds(self) -> list[str]:
        return [str(finding.kind) for finding in self.findings]

    def finding_reasons(self) -> list[str]:
        """One entry per finding, `kind` or `kind/reason`, so the analytics can split by both."""
        return [_finding_label(finding) for finding in self.findings]

    def actionable_finding_kinds(self) -> list[str]:
        return [str(finding.kind) for finding in self.findings if finding.actionable]

    def actionable_finding_reasons(self) -> list[str]:
        return [_finding_label(finding) for finding in self.findings if finding.actionable]


def _finding_label(finding: QueryScanWarning) -> str:
    return f"{finding.kind}/{finding.reason}" if finding.reason is not None else str(finding.kind)


def analyze(
    plans: PlanSet,
    flag: QueryScanFlag,
    *,
    query_kind: str,
    run: RunFacts,
    event_filter: EventFilterOutcome | None = None,
    table_row_averages: dict[str, float] | None = None,
) -> QueryScanResult:
    """`event_filter` is the combined tree-and-plan verdict for the outer execution, from the job.
    None means no verdict shipped, so the outer read's no-event-filter gate falls back to the
    plan's keys alone. A subquery is never classified from the tree, so it always uses that
    fallback.

    `table_row_averages` is empty when the `system.parts` read failed; the persons gate then falls
    back to a raw granule comparison, so the analysis still runs without the metadata query.
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
        run=run,
        range_share=range_share,
        team_granules=plans.team_granules,
        subquery_index=None,
        outer_uses_event_key=False,
        table_row_averages=averages,
        event_filter=event_filter,
    )
    outer_uses_event_key = outer_events is not None and outer_events.uses_event_key()
    for index, subquery in enumerate(plans.subqueries):
        findings += _findings_for_plan(
            subquery,
            flag,
            query_kind=query_kind,
            run=run,
            range_share=None,
            team_granules=plans.team_granules,
            subquery_index=index,
            outer_uses_event_key=outer_uses_event_key,
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
    run: RunFacts,
    range_share: float | None,
    team_granules: int | None,
    subquery_index: int | None,
    outer_uses_event_key: bool,
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

    is_sql = query_kind == SQL_QUERY_KIND
    tree = run.tree
    view_name = tree.view_name if tree is not None else None
    findings: list[QueryScanWarning] = []

    # "All time" reaches the plan as a bound at the project's first event, so only the setting
    # says the person chose no start date; it applies to the outer query, not its subqueries. It is
    # one click to change, so it is reported at any size.
    chose_all_time = run.all_time and subquery_index is None
    unbounded = next((read for read in plan.events_reads() if read.timestamp_bounds().lower is None), None)
    if chose_all_time:
        findings.append(
            build_warning(
                kind=QueryScanFindingKind.NO_START_DATE,
                query_kind=query_kind,
                reason=_all_time_reason(run, is_sql=is_sql),
                evidence=(
                    "The dashboard's date filter is set to All time, so the query starts at the project's first event."
                    if run.dashboard_all_time
                    else "The date range is set to All time, so the query starts at the project's first event."
                ),
                view_name=view_name,
            )
        )
    elif unbounded is not None and _passes_start_date_gate(unbounded, team_granules, flag.start_date_ratio):
        findings.append(
            build_warning(
                kind=QueryScanFindingKind.NO_START_DATE,
                query_kind=query_kind,
                reason=_unbounded_reason(run, is_sql=is_sql),
                evidence=_evidence(unbounded.min_max(), subquery_index),
                subquery_index=subquery_index,
                view_name=view_name,
            )
        )

    no_event_filter, event_reason = _no_event_filter(heaviest, event_filter)
    if no_event_filter and _passes_event_gate(heaviest, range_share, flag.event_ratio):
        if event_reason is None:
            sibling_uses_event_key = outer_uses_event_key or any(
                read is not heaviest and read.uses_event_key() for read in plan.events_reads()
            )
            event_reason = _unfiltered_reason(run, is_sql=is_sql, sibling_uses_event_key=sibling_uses_event_key)
        findings.append(
            build_warning(
                kind=QueryScanFindingKind.NO_EVENT_FILTER,
                query_kind=query_kind,
                reason=event_reason,
                evidence=_evidence(heaviest.primary_key(), subquery_index),
                subquery_index=subquery_index,
                view_name=view_name,
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


def _all_time_reason(run: RunFacts, *, is_sql: bool) -> QueryScanFindingReason:
    """Why an All time run has no start date. A first-time math reads from the first event whatever
    the picker says, so it is by design; otherwise the picker that chose All time is named."""
    if run.all_history_by_design or (run.tree is not None and run.tree.all_history):
        return QueryScanFindingReason.ALL_HISTORY
    if run.dashboard_all_time:
        return QueryScanFindingReason.DASHBOARD_ALL_TIME
    # A SQL insight takes All time through `{filters}`, so the fix is on the insight, not in the SQL.
    return QueryScanFindingReason.FILTERS if is_sql else QueryScanFindingReason.ALL_TIME


def _unbounded_reason(run: RunFacts, *, is_sql: bool) -> QueryScanFindingReason | None:
    """Why a read the plan could not bound has no start date. None is no bound at all, the plain
    case. A bound the tree has but the plan does not is one ClickHouse could not use."""
    tree = run.tree
    if run.all_history_by_design or (tree is not None and tree.all_history):
        return QueryScanFindingReason.ALL_HISTORY
    if run.open_filters_placeholder and is_sql:
        return QueryScanFindingReason.DASHBOARD_ALL_TIME if run.dashboard_all_time else QueryScanFindingReason.FILTERS
    if tree is not None and tree.timestamp_bound:
        return QueryScanFindingReason.BOUND_NOT_USED
    return None


def _unfiltered_reason(run: RunFacts, *, is_sql: bool, sibling_uses_event_key: bool) -> QueryScanFindingReason | None:
    """Why a read with no event condition at all is unfiltered. An unfiltered helper read beside a
    read that names events is the one to filter, even when it counts distinct actors; a property
    condition stands in for an event name unless the query groups by event, whose answer is the
    set of events itself; a count over any event is by design. None is the plain case: nothing in
    the query says which events it is about.
    """
    tree = run.tree
    # An insight's reads are PostHog's own code, so only a SQL author can add a filter to a helper read.
    if is_sql and sibling_uses_event_key:
        return QueryScanFindingReason.HELPER_READ
    if tree is not None and tree.groups_by_event:
        return QueryScanFindingReason.ALL_EVENTS
    if tree is not None and tree.property_filter:
        return QueryScanFindingReason.PROPERTY_FILTER
    if run.all_events_by_design or (tree is not None and tree.counts_any_event):
        return QueryScanFindingReason.ALL_EVENTS
    return None


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


def _passes_start_date_gate(read: PlanTableRead, team_granules: int | None, start_date_ratio: float) -> bool:
    """A small unbounded read, an event filter or a skip index having already pruned it to a sliver
    of the project, is slow for another reason, so a start date is not the advice. Without the
    denominator the size is unknown and the finding stands."""
    share = _share(read.selected_granules(), team_granules)
    return share is None or share >= start_date_ratio


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
