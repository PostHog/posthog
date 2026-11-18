"""Turn ClickHouse's plans into findings and the two shares.

Pure: no ClickHouse, Redis or Celery. A share is a plan's largest events read over a denominator,
the project's events in the plan's date range or over all time. The plan says what was read; the
facts the trigger read off the tree say why. They give each finding its cause, whether it reads this
much by design and where its fix goes, and those pick its wording and whether the person can act.
"""

from posthog.schema import QueryScanFindingKind, QueryScanFixLocation, QueryScanWarning

from posthog.dataclasses import frozen
from posthog.query_scan.event_filter import EventFilterOutcome
from posthog.query_scan.explain import PlanIndex, PlanTableRead, QueryPlan
from posthog.query_scan.findings import SQL_QUERY_KIND, FindingCause, build_warning, explain_evidence, finding_label
from posthog.query_scan.flag import QueryScanFlag
from posthog.query_scan.tree_facts import TreeFacts

__all__ = ["ExplainedPlan", "PlanSet", "QueryScanResult", "RunFacts", "analyze"]


@frozen
class ExplainedPlan:
    """One plan with what it is judged on, the same for the outer query and for a subquery.

    ``range_granules`` is the project's events over the plan's own date range. ``event_filter`` is
    the tree's verdict on the plan's reads folded with the plan's key use, and ``tree`` the other
    facts the trigger read off those reads. Either is None when nothing shipped, and the plan alone
    decides.
    """

    plan: QueryPlan
    range_granules: int | None = None
    event_filter: EventFilterOutcome | None = None
    tree: TreeFacts | None = None


@frozen
class PlanSet:
    """The plans one job produced, and the project's events over all time."""

    outer: ExplainedPlan | None
    subqueries: tuple[ExplainedPlan, ...] = ()
    team_granules: int | None = None


@frozen
class RunFacts:
    """What the trigger knew about the run that the plan cannot show.

    ``all_time`` and ``dashboard_all_time`` say a picker chose All time, and where. The by-design
    flags come from the insight's own settings: a first-time math has to read from the first event,
    and an active-user count on All events has to read every event.
    """

    all_time: bool = False
    dashboard_all_time: bool = False
    all_history_by_design: bool = False
    all_events_by_design: bool = False
    open_filters_placeholder: bool = False


@frozen(eq=False)
class QueryScanResult:
    findings: list[QueryScanWarning]
    explain_ok: bool
    range_share: float | None = None
    project_share: float | None = None

    def finding_kinds(self) -> list[str]:
        return [str(finding.kind) for finding in self.findings]

    def finding_labels(self) -> list[str]:
        return [finding_label(finding) for finding in self.findings]

    def actionable_finding_kinds(self) -> list[str]:
        return [str(finding.kind) for finding in self.findings if finding.actionable]

    def actionable_finding_labels(self) -> list[str]:
        return [finding_label(finding) for finding in self.findings if finding.actionable]


def analyze(
    plans: PlanSet,
    flag: QueryScanFlag,
    *,
    query_kind: str,
    run: RunFacts,
    table_row_averages: dict[str, float] | None = None,
) -> QueryScanResult:
    """`table_row_averages` is empty when the `system.parts` read failed; the persons gate then falls
    back to a raw granule comparison, so the analysis still runs without the metadata query.
    """
    averages = table_row_averages or {}
    if plans.outer is None:
        return QueryScanResult(findings=[], explain_ok=False)

    findings: list[QueryScanWarning] = []
    for subquery_index, explained in [(None, plans.outer), *enumerate(plans.subqueries)]:
        findings += _findings_for_plan(
            explained,
            flag,
            query_kind=query_kind,
            run=run,
            team_granules=plans.team_granules,
            subquery_index=subquery_index,
            table_row_averages=averages,
        )

    numerator = _read_granules(plans.outer)
    return QueryScanResult(
        findings=findings,
        explain_ok=True,
        range_share=_share(numerator, plans.outer.range_granules),
        project_share=_share(numerator, plans.team_granules),
    )


def _findings_for_plan(
    explained: ExplainedPlan,
    flag: QueryScanFlag,
    *,
    query_kind: str,
    run: RunFacts,
    team_granules: int | None,
    subquery_index: int | None,
    table_row_averages: dict[str, float],
) -> list[QueryScanWarning]:
    # A plan that reads the events table more than once is judged on its largest read, except that
    # any read with no start bound is enough for the start-date finding. A lighter read with no event
    # filter goes unmentioned even when it is nearly as large, because gating each read on its own
    # share would cost a denominator per read.
    plan, tree, event_filter = explained.plan, explained.tree, explained.event_filter
    heaviest = plan.heaviest_events_read()
    # A plan that does not read the events table has no denominator and nothing to advise on.
    if heaviest is None:
        return []

    is_sql = query_kind == SQL_QUERY_KIND
    range_share = _share(_read_granules(explained), explained.range_granules)
    view_name = tree.view_name if tree is not None else None
    findings: list[QueryScanWarning] = []

    # "All time" reaches the plan as a bound at the project's first event, so only the setting
    # says the person chose no start date; it applies to the outer query, not its subqueries. It is
    # one click to change, so it is reported at any size.
    chose_all_time = run.all_time and subquery_index is None
    unbounded = max(
        (read for read in plan.events_reads() if read.timestamp_bounds().lower is None),
        key=lambda read: read.selected_granules() or 0,
        default=None,
    )
    if tree is not None and tree.start_date_hidden_from_plan:
        unbounded = None
    reads_all_history = chose_all_time or (
        unbounded is not None and _passes_start_date_gate(unbounded, team_granules, flag.start_date_ratio)
    )
    no_event_filter, event_cause = _no_event_filter(heaviest, event_filter)
    reads_all_events = no_event_filter and _passes_event_gate(heaviest, range_share, flag.event_ratio)
    # All history of a few events, or every event of a short period, is an ordinary by-design read,
    # so there the query's shape is believed. Every event of all history is the most expensive read
    # there is, and the shape cannot tell intent, so there the finding stays a warning.
    believe_shape = not (reads_all_history and reads_all_events)

    if chose_all_time:
        findings.append(
            build_warning(
                kind=QueryScanFindingKind.NO_START_DATE,
                query_kind=query_kind,
                by_design=_all_history_by_design(run, tree, believe_shape=believe_shape),
                fix_location=_all_time_location(run, is_sql=is_sql),
                evidence=(
                    "The dashboard's date filter is set to All time, so the query starts at the project's first event."
                    if run.dashboard_all_time
                    else "The date range is set to All time, so the query starts at the project's first event."
                ),
                view_name=view_name,
            )
        )
    elif unbounded is not None and reads_all_history:
        by_design = _all_history_by_design(run, tree, believe_shape=believe_shape)
        open_filters_location = _open_filters_location(run, is_sql=is_sql, subquery_index=subquery_index)
        fixed_in_the_read = not by_design and open_filters_location is None
        findings.append(
            build_warning(
                kind=QueryScanFindingKind.NO_START_DATE,
                query_kind=query_kind,
                cause=_unbounded_cause(tree) if fixed_in_the_read else None,
                by_design=by_design,
                fix_location=open_filters_location,
                evidence=_evidence(unbounded.min_max(), subquery_index),
                subquery_index=subquery_index,
                view_name=view_name,
            )
        )

    if reads_all_events:
        if event_cause is None:
            sibling_uses_event_key = any(read is not heaviest and read.uses_event_key() for read in plan.events_reads())
            event_cause = _unfiltered_cause(tree, is_sql=is_sql, sibling_uses_event_key=sibling_uses_event_key)
        findings.append(
            build_warning(
                kind=QueryScanFindingKind.NO_EVENT_FILTER,
                query_kind=query_kind,
                cause=event_cause,
                by_design=event_cause is None and _all_events_by_design(run, tree, believe_shape=believe_shape),
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
                subquery_index=subquery_index,
                view_name=view_name,
            )
        )

    return findings


def _read_granules(explained: ExplainedPlan) -> int | None:
    """The granules of the plan's largest events read, for its shares. None when the scan took a
    filter on `event` or `timestamp` out before it asked for the plan, because the filter holds a
    subquery that EXPLAIN would run: the plan's granules are then the read without that filter."""
    hidden_event_filter = explained.event_filter is not None and explained.event_filter.hidden_from_plan
    hidden_start_date = explained.tree is not None and explained.tree.start_date_hidden_from_plan
    events_read = explained.plan.heaviest_events_read()
    if events_read is None or hidden_event_filter or hidden_start_date:
        return None
    return events_read.selected_granules()


def _all_history_by_design(run: RunFacts, tree: TreeFacts | None, *, believe_shape: bool) -> bool:
    """Whether the read has to start at the project's first event. A first-time math says so in the
    insight's settings, which is a choice the person made. A SQL query says so only by its shape."""
    return run.all_history_by_design or (believe_shape and tree is not None and tree.all_history)


def _all_time_location(run: RunFacts, *, is_sql: bool) -> QueryScanFixLocation | None:
    """Where an All time range gets changed. The dashboard's date filter overrides the insight's
    own range. A SQL insight takes All time through `{filters}`, so the fix is on the insight, not
    in the SQL. None is an insight built from pickers, which holds its own range."""
    if run.dashboard_all_time:
        return QueryScanFixLocation.DASHBOARD_DATE_FILTER
    return QueryScanFixLocation.INSIGHT_DATE_RANGE if is_sql else None


def _open_filters_location(run: RunFacts, *, is_sql: bool, subquery_index: int | None) -> QueryScanFixLocation | None:
    """Where a `{filters}` date range nobody set gets changed. None when the fix is in the read
    itself: the query takes no date range through `{filters}`, or the read is a subquery's, because
    nothing says which part of the SQL holds `{filters}`."""
    if not (is_sql and run.open_filters_placeholder) or subquery_index is not None:
        return None
    if run.dashboard_all_time:
        return QueryScanFixLocation.DASHBOARD_DATE_FILTER
    return QueryScanFixLocation.INSIGHT_DATE_RANGE


def _unbounded_cause(tree: TreeFacts | None) -> FindingCause | None:
    """Why a read the plan could not bound has no start date. None is no bound at all, the plain
    case. A bound the tree has but the plan does not is one ClickHouse could not use."""
    return FindingCause.START_DATE_NOT_USED_BY_CLICKHOUSE if tree is not None and tree.timestamp_bound else None


def _unfiltered_cause(tree: TreeFacts | None, *, is_sql: bool, sibling_uses_event_key: bool) -> FindingCause | None:
    """Why a read with no event condition at all is unfiltered. An unfiltered helper read beside a
    read that names events is the one to filter, even when it counts distinct actors; a property
    condition stands in for an event name unless the query groups by event, whose answer is the
    set of events itself. None is the plain case: nothing in the query says which events it is about.
    """
    # An insight's reads are PostHog's own code, so only a SQL author can add a filter to a helper read.
    if is_sql and sibling_uses_event_key:
        return FindingCause.UNFILTERED_HELPER_READ
    if tree is not None and tree.property_filter and not tree.groups_by_event:
        return FindingCause.PROPERTY_FILTER_WITHOUT_EVENT
    return None


def _all_events_by_design(run: RunFacts, tree: TreeFacts | None, *, believe_shape: bool) -> bool:
    """Whether a read with no event condition and no cause has to read every event: the answer is
    the set of events itself, or a count of people or sessions over any event. The insight's
    settings say so as a choice the person made. A SQL query says so only by its shape."""
    shape_says_so = tree is not None and (tree.groups_by_event or tree.counts_any_event)
    return run.all_events_by_design or (believe_shape and shape_says_so)


def _no_event_filter(
    heaviest: PlanTableRead, event_filter: EventFilterOutcome | None
) -> tuple[bool, FindingCause | None]:
    """Whether the heaviest read has no usable event filter, and the cause for the copy. The tree's
    verdict carries the cause when the job shipped one; the read's keys alone name none.
    """
    if event_filter is not None:
        cause = FindingCause(event_filter.reason) if event_filter.reason is not None else None
        return event_filter.classification != "usable", cause
    return not heaviest.uses_event_key(), None


def _passes_start_date_gate(read: PlanTableRead, team_granules: int | None, start_date_ratio: float) -> bool:
    """A small unbounded read, an event filter or a skip index having already pruned it to a sliver
    of the project, is slow for another reason, so a start date is not the advice. Without the
    denominator the size is unknown and the finding stands."""
    share = _share(read.selected_granules(), team_granules)
    return share is None or share >= start_date_ratio


def _passes_event_gate(read: PlanTableRead, range_share: float | None, event_ratio: float) -> bool:
    """With the range share known, gate on it. Without one, because the denominator failed, a skip
    index that already pruned most of the read means an event filter would not help much.
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
