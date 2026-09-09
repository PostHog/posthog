"""The single entry point the query scan job calls once it has the tree, the plan and the counts.

Everything here is pure: no ClickHouse, no Redis, no Celery. The job gathers the inputs and
stores the result; this module decides what the person is told.
"""

from datetime import date, datetime

from posthog.schema import QueryScanWarning

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.printer import print_prepared_ast

from posthog.dataclasses import frozen
from posthog.query_scan.checks.event_filter import EventFilterClass, EventFilterReason, check_event_filter
from posthog.query_scan.checks.persons import check_persons_join
from posthog.query_scan.checks.settings import check_settings
from posthog.query_scan.checks.start_date import StartDateClass, check_start_date
from posthog.query_scan.explain import QueryPlan
from posthog.query_scan.findings import (
    FindingKind,
    FindingReason,
    ScanMeasurements,
    ScanThresholds,
    build_warning,
    event_ratio,
    explain_evidence,
    passes_event_gate,
    passes_persons_gate,
)

__all__ = [
    "QueryScanResult",
    "ScanRange",
    "ScanThresholds",
    "analyze",
    "analyze_settings",
    "check_start_date",
]


@frozen
class ScanRange:
    """The dates the event count covers. ``date_from`` is absent when the query has no start date."""

    date_from: date | None
    date_to: date | None


@frozen(eq=False)
class QueryScanResult:
    findings: list[QueryScanWarning]
    explain_ok: bool
    event_ratio: float | None = None
    event_filter_class: EventFilterClass | None = None
    event_filter_reason: EventFilterReason | None = None
    start_date_class: StartDateClass | None = None
    range: ScanRange | None = None

    def finding_kinds(self) -> list[str]:
        return [str(finding.kind) for finding in self.findings]


def analyze(
    prepared_tree: ast.AST,
    context: HogQLContext,
    *,
    plan: QueryPlan | None,
    rows_read: int,
    duration_ms: int,
    killed: bool,
    events_in_range: int | None,
    min_timestamp: datetime | None,
    person_rows: int | None,
    has_filters_placeholder: bool,
    thresholds: ScanThresholds,
) -> QueryScanResult:
    start_date = check_start_date(prepared_tree, has_filters_placeholder=has_filters_placeholder)
    event_filter = check_event_filter(prepared_tree, plan)
    persons = check_persons_join(context)

    scan_range = ScanRange(date_from=start_date.date_from, date_to=start_date.date_to)
    measurements = ScanMeasurements(
        rows_read=rows_read,
        duration_ms=duration_ms,
        killed=killed,
        events_in_range=events_in_range,
        person_rows=person_rows,
        days=_span_in_days(scan_range, min_timestamp),
    )

    findings: list[QueryScanWarning] = []

    if event_filter.classification != "usable" and passes_event_gate(measurements, thresholds):
        kind = (
            FindingKind.NO_EVENT_FILTER if event_filter.classification == "none" else FindingKind.EVENT_FILTER_NOT_USED
        )
        reason = FindingReason(event_filter.reason) if event_filter.reason is not None else None
        findings.append(
            build_warning(
                kind=kind,
                reason=reason,
                measurements=measurements,
                clause=_print_clause(event_filter.clause, context),
                evidence=explain_evidence(plan),
            )
        )

    if start_date.classification != "bound":
        findings.append(
            build_warning(
                kind=FindingKind.NO_START_DATE,
                reason=FindingReason(start_date.reason) if start_date.reason is not None else None,
                measurements=measurements,
                clause=_print_clause(start_date.clause, context),
            )
        )

    if persons.unfiltered and passes_persons_gate(measurements, thresholds):
        findings.append(build_warning(kind=FindingKind.PERSONS_JOIN, measurements=measurements))

    return QueryScanResult(
        findings=findings,
        explain_ok=plan is not None,
        event_ratio=event_ratio(rows_read, events_in_range),
        event_filter_class=event_filter.classification,
        event_filter_reason=event_filter.reason,
        start_date_class=start_date.classification,
        range=scan_range,
    )


def analyze_settings(
    query: dict[str, object],
    *,
    date_from: date | None,
    date_to: date | None,
    rows_read: int,
    duration_ms: int,
    killed: bool = False,
    events_in_range: int | None,
    thresholds: ScanThresholds,
) -> QueryScanResult:
    """The checks for insight kinds built from pickers rather than SQL."""
    settings = check_settings(query)
    scan_range = ScanRange(date_from=date_from, date_to=date_to)
    measurements = ScanMeasurements(
        rows_read=rows_read,
        duration_ms=duration_ms,
        killed=killed,
        events_in_range=events_in_range,
        days=_span_in_days(scan_range, None),
    )

    findings: list[QueryScanWarning] = []
    if settings.all_events and passes_event_gate(measurements, thresholds):
        findings.append(build_warning(kind=FindingKind.ALL_EVENTS, measurements=measurements))
    if settings.all_time:
        findings.append(build_warning(kind=FindingKind.ALL_TIME, measurements=measurements))

    return QueryScanResult(
        findings=findings,
        explain_ok=False,
        event_ratio=event_ratio(rows_read, events_in_range),
        range=scan_range,
    )


def _span_in_days(scan_range: ScanRange, min_timestamp: datetime | None) -> int | None:
    """How many days of data the query covered.

    With no start date the range has no lower end, so the earliest timestamp the count query
    returned stands in for it.
    """
    if scan_range.date_to is None:
        return None
    start = scan_range.date_from or (min_timestamp.date() if min_timestamp is not None else None)
    if start is None:
        return None
    return max((scan_range.date_to - start).days + 1, 1)


def _print_clause(clause: ast.Expr | None, context: HogQLContext) -> str | None:
    """The offending condition printed back as HogQL, so the person can search for it.

    The tree is already lowered for ClickHouse, so a clause can hold a node the HogQL printer
    rejects. The warning is still worth showing without it.
    """
    if clause is None:
        return None
    try:
        return print_prepared_ast(node=clause, context=context, dialect="hogql")
    except Exception:
        return None
