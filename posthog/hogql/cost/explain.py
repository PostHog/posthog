"""The scan estimate and the index verdicts, rendered as one plan a person can read top to bottom.

The estimate says how much each table is read. The index report says, per property filter, whether an index can
skip any of it. On their own each is a table of facts; together, in the order the query runs, they answer "why
is this slow": which scan carries the cost, which filter reads every row anyway, and what to change.
"""

from typing import Literal

from posthog.hogql.cost.estimate import FilterEstimate, ScanEstimate, TableScanEstimate
from posthog.hogql.index_eligibility import IndexEligibilityReport, PredicateIndexEligibility, PredicateIndexVerdict
from posthog.hogql.property_planner import PropertyScope

from posthog.dataclasses import frozen

CostPlanStepKind = Literal["scan", "filter", "join"]


@frozen
class CostPlanStep:
    kind: CostPlanStepKind
    # One line, the way an EXPLAIN prints it.
    message: str
    # The rest of the story for a reader who expands the line.
    detail: str | None = None
    table: str | None = None
    rows: int | None = None
    fix: str | None = None
    ai_fix_prompt: str | None = None


def build_cost_plan(estimate: ScanEstimate | None, report: IndexEligibilityReport | None) -> tuple[CostPlanStep, ...]:
    """Scans in FROM order, each followed by the filters that apply to it, then one join line when there are several."""
    if estimate is None:
        return ()
    predicates = list(report.predicates) if report is not None else []
    steps: list[CostPlanStep] = []
    for table in estimate.tables:
        steps.append(_scan_step(table))
        for predicate in _filters_for(table, estimate, predicates):
            steps.append(_filter_step(predicate, table))
    if len(estimate.tables) > 1:
        steps.append(
            CostPlanStep(
                kind="join",
                message=f"Join {len(estimate.tables)} tables. Rows after the join are not estimated.",
                detail="The estimate sums what each side reads. How many rows survive the join depends on the keys, "
                "which the planner does not model yet.",
            )
        )
    return tuple(steps)


def _scan_step(table: TableScanEstimate) -> CostPlanStep:
    if table.precision == "measured":
        return CostPlanStep(
            kind="scan",
            table=table.name,
            rows=table.rows,
            message=f"Scan {table.name}, about {_rows(table.rows)} ({_range(table)})",
            detail=_measured_detail(table),
        )
    if table.precision == "size_only":
        size = ", ".join(
            part for part in (_rows(table.rows) if table.rows is not None else None, _bytes(table.bytes)) if part
        )
        return CostPlanStep(
            kind="scan",
            table=table.name,
            rows=table.rows,
            message=f"Scan {table.name}, up to {size} on disk",
            detail="The whole table as it was last measured. How much of it the query reads is not estimated.",
        )
    return CostPlanStep(
        kind="scan",
        table=table.name,
        message=f"Scan {table.name}, size unknown",
        detail="No statistics for this table yet, so it is not counted in the total.",
    )


def _measured_detail(table: TableScanEstimate) -> str:
    if table.source == "events":
        events = f"narrowed to {', '.join(table.events)}" if table.events else "every event"
        return f"Events per day for the team, scaled to the timestamp range and {events}."
    return "Rows per day for the team, scaled to the range on the session start time."


def _filters_for(
    table: TableScanEstimate, estimate: ScanEstimate, predicates: list[PredicateIndexEligibility]
) -> list[PredicateIndexEligibility]:
    """The predicates that filter this scan.

    The index report does not say which table a predicate reads, so the property scope decides: an event
    property filters the first events scan, a person or group property the first scan of that table, or the
    first events scan when there is none, because that is where those properties are read from otherwise.
    """
    first_of: dict[str, TableScanEstimate] = {}
    for candidate in estimate.tables:
        first_of.setdefault(candidate.name, candidate)
    events_scan = next((candidate for candidate in estimate.tables if candidate.source == "events"), None)
    matched: list[PredicateIndexEligibility] = []
    for predicate in predicates:
        target = _scan_for_scope(predicate.scope, first_of, events_scan)
        if target is table:
            matched.append(predicate)
    return matched


def _scan_for_scope(
    scope: PropertyScope, first_of: dict[str, TableScanEstimate], events_scan: TableScanEstimate | None
) -> TableScanEstimate | None:
    if scope == PropertyScope.PERSON:
        return first_of.get("persons") or first_of.get("raw_persons") or events_scan
    if scope == PropertyScope.GROUP:
        return first_of.get("groups") or first_of.get("raw_groups") or events_scan
    return events_scan


def _filter_step(predicate: PredicateIndexEligibility, table: TableScanEstimate) -> CostPlanStep:
    name = f"{'person.' if predicate.scope == PropertyScope.PERSON else ''}{predicate.property_name}"
    operator = "=" if predicate.operator.value == "==" else predicate.operator.value
    head = f"Filter {name} {operator} …"
    modelled = _modelled_filter(predicate, table)
    if modelled is not None and modelled.granules_read is not None:
        skipped = 1 - modelled.granules_read
        if skipped >= 0.995:
            # A rounded 100% would claim the filter reads nothing at all.
            effect = "skips over 99% of the scan"
        elif skipped >= 0.005:
            effect = f"skips about {skipped:.0%} of the scan"
        else:
            effect = "skips almost nothing"
    elif predicate.verdict == PredicateIndexVerdict.INDEXED:
        effect = "has an index, how much it skips is not estimated"
    elif predicate.verdict == PredicateIndexVerdict.BLOCKED:
        effect = "index unused, reads every row"
    else:
        effect = "reads every row"
    return CostPlanStep(
        kind="filter",
        table=table.name,
        message=f"{head} {effect}",
        detail=predicate.message,
        fix=predicate.fix,
        ai_fix_prompt=predicate.ai_fix_prompt,
    )


def _modelled_filter(predicate: PredicateIndexEligibility, table: TableScanEstimate) -> FilterEstimate | None:
    if predicate.scope != PropertyScope.EVENT:
        return None
    return next((f for f in table.filters if f.property_name == predicate.property_name), None)


def _rows(rows: int | None) -> str:
    if rows is None:
        return "an unknown number of rows"
    for unit, label in ((1_000_000_000, "B"), (1_000_000, "M"), (1_000, "K")):
        if rows >= unit:
            value = rows / unit
            return f"{value:.1f}{label} rows" if value < 10 else f"{value:.0f}{label} rows"
    return f"{rows} rows"


def _bytes(size: int | None) -> str | None:
    if size is None:
        return None
    for unit, label in ((1024**4, "TB"), (1024**3, "GB"), (1024**2, "MB"), (1024, "KB")):
        if size >= unit:
            return f"{size / unit:.1f} {label}"
    return f"{size} B"


def _range(table: TableScanEstimate) -> str:
    if table.days is None:
        return "range unknown"
    if table.time_range == "open":
        return "no date range, assuming a year"
    return f"{round(table.days)} days" if table.days >= 2 else f"{round(table.days * 24)} hours"
