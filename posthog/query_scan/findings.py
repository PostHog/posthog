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
    # counts towards it.
    rows_read: int
    duration_ms: int
    events_in_range: int | None = None
    person_rows: int | None = None
    # The events-table share of `rows_read`, which is what the event ratio compares against the
    # count of events in the range. None when the whole read came from the events table.
    events_rows_read: int | None = None


@frozen
class _Copy:
    lead: str
    advice: str
    fix: str


_COPY: dict[tuple[FindingKind, FindingReason | None], _Copy] = {
    (FindingKind.NO_EVENT_FILTER, None): _Copy(
        lead=(
            "Queries are fastest when they name a fixed set of events. This query has no event filter, so it "
            "reads every event you have ever sent, which is slow."
        ),
        advice="If the question is about specific events, add `WHERE event IN ('…')` naming them.",
        fix="Add an event filter naming the events this question is about. Change nothing else.",
    ),
    (FindingKind.EVENT_FILTER_NOT_USED, FindingReason.IN_OR): _Copy(
        lead=(
            "Queries are fastest when they name a fixed set of events. This query names events only inside an OR "
            "with another condition{clause}, so that filter cannot be used and it still reads every event, which "
            "is slow."
        ),
        advice="Put the event filter outside the OR: `WHERE event IN ('…') AND (… OR …)`.",
        fix=(
            "If every branch of the OR names events, move the event filter out so it stands on its own, and "
            "change nothing else. If moving it would change which rows match, leave the query as it is and "
            "explain that ClickHouse cannot use an event filter inside an OR."
        ),
    ),
    (FindingKind.EVENT_FILTER_NOT_USED, FindingReason.WRAPPED): _Copy(
        lead=(
            "Queries are fastest when they compare `event` directly to fixed names. This query wraps `event` in a "
            "function{clause}, so that filter cannot be used and it still reads every event, which is slow."
        ),
        advice="Compare `event` directly to the names.",
        fix=(
            "If the function around `event` does not change which events match, compare `event` directly to "
            "the names and change nothing else. If it does, leave the query as it is and explain that "
            "ClickHouse cannot use an event filter with a function around the column."
        ),
    ),
    (FindingKind.EVENT_FILTER_NOT_USED, FindingReason.NEGATED): _Copy(
        lead=(
            "Queries are fastest when they explicitly enumerate the events they want. This query only excludes "
            "events{clause}, so that filter cannot be used and it still reads most events, which is slow."
        ),
        advice="Explicitly enumerate the events you want instead.",
        fix=(
            "If the events to keep can be named, replace the exclusion with a filter that names them, and "
            "change nothing else. If they cannot, leave the query as it is and explain that ClickHouse "
            "cannot use an event filter that excludes events."
        ),
    ),
    (FindingKind.EVENT_FILTER_NOT_USED, FindingReason.DYNAMIC): _Copy(
        lead=(
            "Queries are fastest when they compare `event` to fixed names. This query compares `event` to another "
            "column or a subquery{clause}, so that filter cannot be used and it still reads every event, which is "
            "slow."
        ),
        advice="Compare `event` to fixed names.",
        fix=(
            "If the column or subquery stands for a fixed set of event names, compare `event` to those names "
            "and change nothing else. If it does not, leave the query as it is and explain that ClickHouse "
            "cannot use an event filter that compares `event` to data."
        ),
    ),
    (FindingKind.EVENT_FILTER_NOT_USED, FindingReason.NOT_PRUNED): _Copy(
        lead=(
            "Queries are fastest when they compare `event` directly to fixed names. This query has an event "
            "filter{clause}, but it could not be used, so it still read every event, which is slow."
        ),
        advice="Compare `event` directly to fixed names, outside any OR.",
        fix="Compare `event` directly to fixed event names, outside any OR. Change nothing else.",
    ),
    (FindingKind.NO_START_DATE, None): _Copy(
        lead=(
            "Queries are fastest when they start from a recent date. This query has no start date, so it reads "
            "all your data back to the beginning, which is slow."
        ),
        advice="If you only need recent data, add `timestamp >= now() - interval 30 day` or the range you need.",
        fix=(
            "Add a start date on `timestamp`, for example `timestamp >= now() - interval 30 day`. Change nothing else."
        ),
    ),
    (FindingKind.NO_START_DATE, FindingReason.COLUMN): _Copy(
        lead=(
            "Queries are fastest when they start from a fixed date. This query's start date comes from another "
            "column{clause}, so older data cannot be skipped and it reads everything back to the beginning, which "
            "is slow."
        ),
        advice="Compare `timestamp` to a fixed date, for example `timestamp >= now() - interval 30 day`.",
        fix="Compare `timestamp` to a fixed start date instead of another column. Change nothing else.",
    ),
    (FindingKind.NO_START_DATE, FindingReason.FILTERS): _Copy(
        lead=(
            "Queries are fastest when they start from a recent date. No date range is set on this insight or "
            "dashboard, so this query reads all your data back to the beginning, which is slow."
        ),
        advice="Set a date range on the insight or the dashboard.",
        fix="Set a date range on the insight or the dashboard. The SQL does not need to change.",
    ),
    (FindingKind.PERSONS_JOIN, None): _Copy(
        lead=(
            "Queries are fastest when they take person details from the events table. This query joins the "
            "persons table, so every run reads every person in your project, which is slow."
        ),
        advice="Read person properties from the events table instead, for example `person.properties.email`.",
        fix=(
            "Read person properties from the events table, for example `person.properties.email`, instead "
            "of joining the persons table. Change nothing else."
        ),
    ),
    (FindingKind.ALL_EVENTS, None): _Copy(
        lead=(
            "Insights are fastest when they look at a fixed set of events. This insight looks at all events, so "
            "it reads everything you have ever sent, which is slow."
        ),
        advice="Pick specific events if the question is about some of them.",
        fix="Pick the events this insight is about instead of All events.",
    ),
    (FindingKind.ALL_TIME, None): _Copy(
        lead=(
            "Insights are fastest when they start from a recent date. This insight has no start date, so it reads "
            "all your data back to the beginning, which is slow."
        ),
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
    if measurements.events_in_range is None or measurements.events_in_range <= 0:
        return False
    rows_read = measurements.events_rows_read if measurements.events_rows_read is not None else measurements.rows_read
    return rows_read >= thresholds.event_ratio * measurements.events_in_range


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
    # The clause is the person's own text, so it sits inside the sentence that describes it.
    lead = copy.lead.format(clause=f" (`{clause}`)" if clause else "")
    return QueryScanWarning(
        kind=kind,
        reason=reason,
        message=f"{lead} {copy.advice}",
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
    primary_keys = [key for read in plan.events_reads() if (key := read.primary_key()) is not None]
    if not primary_keys:
        return None
    # The finding is about a read that could not prune on `event`, so name that read when the plan
    # holds one. With several reads the plan does not say which one the finding came from.
    primary_key = next((key for key in primary_keys if "event" not in key.keys), primary_keys[0])
    keys = ", ".join(primary_key.keys)
    if primary_key.initial_granules is None or primary_key.selected_granules is None:
        return f"ClickHouse used the primary key columns {keys}."
    return (
        f"ClickHouse used the primary key columns {keys} and kept "
        f"{primary_key.selected_granules:,} of {primary_key.initial_granules:,} granules."
    )


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
