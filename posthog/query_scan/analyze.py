"""The single entry point the query scan job calls once it has the tree, the plan and the counts.

Everything here is pure: no ClickHouse, no Redis, no Celery.
"""

from datetime import date

from posthog.schema import QueryScanWarning

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.parser import parse_select
from posthog.hogql.visitor import TraversingVisitor

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
from posthog.query_scan.tree import find_events_reads

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
    events_in_range: int | None,
    person_rows: int | None,
    has_filters_placeholder: bool,
    thresholds: ScanThresholds,
    source: str | None = None,
) -> QueryScanResult:
    """`source` is the HogQL the person typed, when there is one. Findings quote their clause from it."""
    typed_spans = _typed_spans(source)
    start_date = check_start_date(prepared_tree, has_filters_placeholder=has_filters_placeholder)
    event_filter = check_event_filter(prepared_tree, plan)
    persons = check_persons_join(context)
    reads_events = bool(find_events_reads(prepared_tree))

    # `rows_read` covers every table, so the person rows come off it to estimate the events side.
    events_rows_read = (
        max(rows_read - person_rows, 0) if persons.reads_persons and person_rows is not None else rows_read
    )

    scan_range = ScanRange(date_from=start_date.date_from, date_to=start_date.date_to)
    measurements = ScanMeasurements(
        rows_read=rows_read,
        duration_ms=duration_ms,
        events_in_range=events_in_range,
        person_rows=person_rows,
        events_rows_read=events_rows_read,
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
                clause=_quote_clause(event_filter.clause, source, typed_spans),
                evidence=explain_evidence(plan),
            )
        )

    if start_date.classification != "bound":
        findings.append(
            build_warning(
                kind=FindingKind.NO_START_DATE,
                reason=FindingReason(start_date.reason) if start_date.reason is not None else None,
                measurements=measurements,
                clause=_quote_clause(start_date.clause, source, typed_spans),
            )
        )

    # The advice is to read person properties from the events table, which needs an events read.
    if persons.unfiltered and reads_events and passes_persons_gate(measurements, thresholds):
        findings.append(build_warning(kind=FindingKind.PERSONS_JOIN, measurements=measurements))

    return QueryScanResult(
        findings=findings,
        explain_ok=plan is not None,
        event_ratio=event_ratio(events_rows_read, events_in_range),
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
    events_in_range: int | None,
    thresholds: ScanThresholds,
) -> QueryScanResult:
    """The checks for insight kinds built from pickers rather than SQL."""
    settings = check_settings(query)
    scan_range = ScanRange(date_from=date_from, date_to=date_to)
    measurements = ScanMeasurements(
        rows_read=rows_read,
        duration_ms=duration_ms,
        events_in_range=events_in_range,
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


class _SpanCollector(TraversingVisitor):
    def __init__(self) -> None:
        super().__init__()
        self.spans: set[tuple[int, int]] = set()

    def visit(self, node: ast.AST | None) -> None:
        if node is not None and node.start is not None and node.end is not None:
            self.spans.add((node.start, node.end))
        super().visit(node)


def _typed_spans(source: str | None) -> frozenset[tuple[int, int]]:
    """The source offsets of every node in the typed query, so a clause can be cut from it."""
    if source is None:
        return frozenset()
    collector = _SpanCollector()
    try:
        collector.visit(parse_select(source))
    except Exception:
        return frozenset()
    return frozenset(collector.spans)


def _quote_clause(clause: ast.Expr | None, source: str | None, typed_spans: frozenset[tuple[int, int]]) -> str | None:
    """The offending condition in the person's own words.

    The checks run on the tree lowered for ClickHouse, and that tree printed back (`or(equals(…))`,
    materialized column names) is not what the person typed. Nodes keep the offsets they were parsed
    at, so the condition is cut from the typed query instead. A condition inlined from a saved view
    carries the view's offsets, so only a span the typed query also has is quoted.
    """
    if clause is None or source is None or clause.start is None or clause.end is None:
        return None
    if (clause.start, clause.end) not in typed_spans:
        return None
    return source[clause.start : clause.end].strip()
