"""Turn a check outcome into the warning a person reads, and gate it by the ratios.

The floor already said the person waited. The ratios say whether the unfiltered thing was a
large share of what the query read, so advice that would not have helped stays quiet.
"""

from posthog.schema import QueryScanFindingKind, QueryScanFindingReason, QueryScanWarning

from posthog.dataclasses import frozen
from posthog.query_scan.explain import QueryPlan

FindingKind = QueryScanFindingKind
FindingReason = QueryScanFindingReason


@frozen
class ScanThresholds:
    """Ratio gates, filled from the feature flag payload."""

    event_ratio: float = 0.10
    persons_ratio: float = 0.5


@frozen
class ScanMeasurements:
    """What the run cost, and what it is measured against."""

    # Every row ClickHouse read for the query, across every table it touched, so a joined table
    # counts towards it. The copy says rows rather than events for that reason.
    rows_read: int
    duration_ms: int
    killed: bool = False
    events_in_range: int | None = None
    person_rows: int | None = None
    days: int | None = None


@frozen
class _Copy:
    lead: str
    killed_lead: str
    advice: str
    fix: str


_KILLED_NUMBERS = "ClickHouse stopped it after {secs} s, having read {rows} rows."

_START_DATE_ADVICE = "If you only need recent data, add `timestamp >= now() - interval 30 day` or the range you need."

_COPY: dict[tuple[FindingKind, FindingReason | None], _Copy] = {
    (FindingKind.NO_EVENT_FILTER, None): _Copy(
        lead="This query has no event filter, so it read {rows} rows in {secs} s.",
        killed_lead="This query has no event filter. " + _KILLED_NUMBERS,
        advice="If the question is about specific events, add `WHERE event IN ('…')` naming them.",
        fix="Add an event filter naming the events this question is about. Change nothing else.",
    ),
    (FindingKind.EVENT_FILTER_NOT_USED, FindingReason.IN_OR): _Copy(
        lead=(
            "This query has an event filter, but it is inside an OR with another condition, so "
            "ClickHouse could not use it. It read {rows} rows in {secs} s."
        ),
        killed_lead=(
            "This query has an event filter, but it is inside an OR with another condition, so "
            "ClickHouse could not use it. " + _KILLED_NUMBERS
        ),
        advice="Put the event filter outside the OR: `WHERE event IN ('…') AND (… OR …)`.",
        fix="Move the event filter out of the OR so it stands on its own. Change nothing else.",
    ),
    (FindingKind.EVENT_FILTER_NOT_USED, FindingReason.WRAPPED): _Copy(
        lead=(
            "This query has an event filter, but the event column is wrapped in a function, so "
            "ClickHouse could not use it. It read {rows} rows in {secs} s."
        ),
        killed_lead=(
            "This query has an event filter, but the event column is wrapped in a function, so "
            "ClickHouse could not use it. " + _KILLED_NUMBERS
        ),
        advice="Compare `event` directly to the names.",
        fix="Compare `event` directly to the event names, with no function around it. Change nothing else.",
    ),
    (FindingKind.EVENT_FILTER_NOT_USED, FindingReason.NEGATED): _Copy(
        lead=(
            "This query has an event filter, but it excludes events instead of naming them, so "
            "ClickHouse could not use it. It read {rows} rows in {secs} s."
        ),
        killed_lead=(
            "This query has an event filter, but it excludes events instead of naming them, so "
            "ClickHouse could not use it. " + _KILLED_NUMBERS
        ),
        advice="Name the events you want.",
        fix="Replace the exclusion with a filter that names the events to keep. Change nothing else.",
    ),
    (FindingKind.EVENT_FILTER_NOT_USED, FindingReason.DYNAMIC): _Copy(
        lead=(
            "This query has an event filter, but it compares `event` to another column or a subquery, "
            "so ClickHouse could not use it. It read {rows} rows in {secs} s."
        ),
        killed_lead=(
            "This query has an event filter, but it compares `event` to another column or a subquery, "
            "so ClickHouse could not use it. " + _KILLED_NUMBERS
        ),
        advice="Compare `event` to fixed names.",
        fix="Compare `event` to fixed event names instead of a column or a subquery. Change nothing else.",
    ),
    (FindingKind.EVENT_FILTER_NOT_USED, FindingReason.NOT_PRUNED): _Copy(
        lead=("This query has an event filter but ClickHouse did not use it. It read {rows} rows in {secs} s."),
        killed_lead="This query has an event filter but ClickHouse did not use it. " + _KILLED_NUMBERS,
        advice="Compare `event` directly to fixed names, outside any OR.",
        fix="Compare `event` directly to fixed event names, outside any OR. Change nothing else.",
    ),
    (FindingKind.NO_START_DATE, None): _Copy(
        lead="This query has no start date, so it read {rows} rows across {span} in {secs} s.",
        killed_lead="This query has no start date, so it covers {span}. " + _KILLED_NUMBERS,
        advice=_START_DATE_ADVICE,
        fix=(
            "Add a start date on `timestamp`, for example `timestamp >= now() - interval 30 day`. Change nothing else."
        ),
    ),
    (FindingKind.NO_START_DATE, FindingReason.COLUMN): _Copy(
        lead=(
            "This query's start date compares two columns, so ClickHouse cannot skip data with it. "
            "It read {rows} rows across {span} in {secs} s."
        ),
        killed_lead=(
            "This query's start date compares two columns, so ClickHouse cannot skip data with it. "
            "It covers {span}. " + _KILLED_NUMBERS
        ),
        advice=_START_DATE_ADVICE,
        fix="Compare `timestamp` to a fixed start date instead of another column. Change nothing else.",
    ),
    (FindingKind.NO_START_DATE, FindingReason.FILTERS): _Copy(
        lead=(
            "No date range is set for this insight or dashboard, so this query read {rows} rows across "
            "all your data in {secs} s."
        ),
        killed_lead=(
            "No date range is set for this insight or dashboard, so this query covers all your data. " + _KILLED_NUMBERS
        ),
        advice="Set a date range on the insight or the dashboard.",
        fix="Set a date range on the insight or the dashboard. The SQL does not need to change.",
    ),
    (FindingKind.PERSONS_JOIN, None): _Copy(
        lead="This query joins the persons table, which reads all {person_rows} person rows on every run.",
        killed_lead=(
            "This query joins the persons table, which reads all {person_rows} person rows on every run. "
            + _KILLED_NUMBERS
        ),
        advice="Read person properties from the events table instead, for example `person.properties.email`.",
        fix=(
            "Read person properties from the events table, for example `person.properties.email`, instead "
            "of joining the persons table. Change nothing else."
        ),
    ),
    (FindingKind.ALL_EVENTS, None): _Copy(
        lead="This insight looks at all events, so it read {rows} rows in {secs} s.",
        killed_lead="This insight looks at all events. " + _KILLED_NUMBERS,
        advice="Pick specific events if the question is about some of them.",
        fix="Pick the events this insight is about instead of All events.",
    ),
    (FindingKind.ALL_TIME, None): _Copy(
        lead="This insight has no start date, so it read {rows} rows across all your data in {secs} s.",
        killed_lead="This insight has no start date. " + _KILLED_NUMBERS,
        advice="Set a date range if you only need recent data.",
        fix="Set a date range on the insight instead of All time.",
    ),
}


def event_ratio(rows_read: int, events_in_range: int | None) -> float | None:
    if events_in_range is None or events_in_range <= 0:
        return None
    return rows_read / events_in_range


def passes_event_gate(measurements: ScanMeasurements, thresholds: ScanThresholds) -> bool:
    """Below the ratio, something else already pruned the read, so an event filter would not
    have saved much."""
    if measurements.events_in_range is None:
        return False
    return measurements.rows_read >= thresholds.event_ratio * measurements.events_in_range


def passes_persons_gate(measurements: ScanMeasurements, thresholds: ScanThresholds) -> bool:
    if measurements.person_rows is None:
        return False
    return measurements.person_rows >= thresholds.persons_ratio * measurements.rows_read


def build_warning(
    *,
    kind: FindingKind,
    measurements: ScanMeasurements,
    reason: FindingReason | None = None,
    clause: str | None = None,
    evidence: str | None = None,
) -> QueryScanWarning:
    copy = _COPY[(kind, reason)]
    lead = copy.killed_lead if measurements.killed else copy.lead
    return QueryScanWarning(
        kind=kind,
        reason=reason,
        message=f"{_render(lead, measurements)} {copy.advice}",
        fix=copy.fix,
        clause=clause,
        evidence=evidence,
        rows_read=measurements.rows_read,
        duration_ms=measurements.duration_ms,
        events_in_range=measurements.events_in_range,
    )


def explain_evidence(plan: QueryPlan | None) -> str | None:
    """What ClickHouse reported about the events read, for the person to check against."""
    if plan is None:
        return None
    for read in plan.events_reads():
        primary_key = read.primary_key()
        if primary_key is None:
            continue
        keys = ", ".join(primary_key.keys)
        if primary_key.initial_granules is None or primary_key.selected_granules is None:
            return f"ClickHouse used the primary key columns {keys}."
        return (
            f"ClickHouse used the primary key columns {keys} and kept "
            f"{primary_key.selected_granules:,} of {primary_key.initial_granules:,} granules."
        )
    return None


def format_rows(rows: int) -> str:
    if rows >= 1_000_000_000_000:
        return f"{rows / 1_000_000_000_000:.1f} trillion"
    if rows >= 1_000_000_000:
        return f"{rows / 1_000_000_000:.1f} billion"
    if rows >= 1_000_000:
        return f"{rows / 1_000_000:.1f} million"
    return f"{rows:,}"


def format_seconds(duration_ms: int) -> str:
    return f"{duration_ms / 1000:.1f}"


def _render(template: str, measurements: ScanMeasurements) -> str:
    return template.format(
        rows=format_rows(measurements.rows_read),
        secs=format_seconds(measurements.duration_ms),
        span=_format_span(measurements.days),
        person_rows=format_rows(measurements.person_rows or 0),
    )


def _format_span(days: int | None) -> str:
    # Without a start date the query covered everything the project has, and the count query is
    # what tells us how far back that goes. If it could not, say so in words instead of a number.
    if days is None:
        return "all your data"
    return f"{days:,} days of data"
