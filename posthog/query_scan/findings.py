"""Turn an analysis outcome into the warning a person reads.

The copy is the wording decided for the spec. A no-event-filter or no-start-date finding reads
differently for raw SQL than for an insight built from pickers, so the query kind chooses which
wording to use.
"""

from posthog.schema import QueryScanFindingKind, QueryScanFindingReason, QueryScanWarning

from posthog.dataclasses import frozen
from posthog.query_scan.flag import DEFAULT_EVENT_RATIO, DEFAULT_PERSONS_RATIO

FindingKind = QueryScanFindingKind
FindingReason = QueryScanFindingReason

# The kind used by `to_query()` for a raw HogQL query. Any other kind is an insight built from
# pickers, so the advice names the picker instead of a clause to add.
_SQL_QUERY_KIND = "HogQLQuery"


@frozen
class ScanThresholds:
    """Ratio gates, filled from the feature flag payload."""

    event_ratio: float = DEFAULT_EVENT_RATIO
    persons_ratio: float = DEFAULT_PERSONS_RATIO


@frozen
class ScanMeasurements:
    # Every row ClickHouse read for the query, across every table it touched, so a joined table
    # counts towards it. Both come from the run the person made, not from the plan.
    rows_read: int
    duration_ms: int


@frozen
class _Copy:
    lead: str
    advice: str
    fix: str


_NO_EVENT_FILTER_SQL = _Copy(
    lead=(
        "Queries are fastest when they name a fixed set of events. This query has no event filter, so it "
        "reads every event you have ever sent, which is slow."
    ),
    advice="If the question is about specific events, add `WHERE event IN ('…')` naming them.",
    fix=(
        "If the query makes clear which events the question is about, add an event filter naming them and "
        "change nothing else. If it does not, leave the query as it is; only the person knows which events "
        "the question is about."
    ),
)

_NO_EVENT_FILTER_INSIGHT = _Copy(
    lead=(
        "Insights are fastest when they look at a fixed set of events. This insight looks at all events, so "
        "it reads everything you have ever sent, which is slow."
    ),
    advice="Pick specific events if the question is about some of them.",
    fix="Pick the events this insight is about instead of All events.",
)

_NO_START_DATE_SQL = _Copy(
    lead=(
        "Queries are fastest when they start from a recent date. This query has no start date, so it reads "
        "all your data back to the beginning, which is slow."
    ),
    advice="If you only need recent data, add `timestamp >= now() - interval 30 day` or the range you need.",
    fix=(
        "Add a start date on `timestamp` relative to now, for example `timestamp >= now() - interval 30 day`. "
        "Never write a specific calendar date. Change nothing else."
    ),
)

_NO_START_DATE_FILTERS = _Copy(
    lead=(
        "Queries are fastest when they start from a recent date. No date range is set on this insight or "
        "dashboard, so this query reads all your data back to the beginning, which is slow."
    ),
    advice="Set a date range on the insight or the dashboard.",
    fix="Set a date range on the insight or the dashboard. The SQL does not need to change.",
)

_NO_START_DATE_INSIGHT = _Copy(
    lead=(
        "Insights are fastest when they start from a recent date. This insight has no start date, so it reads "
        "all your data back to the beginning, which is slow."
    ),
    advice="Set a date range if you only need recent data.",
    fix="Set a date range on the insight instead of All time.",
)

_PERSONS_JOIN = _Copy(
    lead=(
        "Queries are fastest when they take person details from the events table. This query joins the "
        "persons table, so every run reads every person in your project, which is slow."
    ),
    advice="Read person properties from the events table instead, for example `person.properties.email`.",
    fix=(
        "Read person properties from the events table, for example `person.properties.email`, instead "
        "of joining the persons table. Change nothing else."
    ),
)


def _copy_for(kind: FindingKind, reason: FindingReason | None, *, is_sql: bool) -> _Copy:
    if kind == FindingKind.NO_EVENT_FILTER:
        return _NO_EVENT_FILTER_SQL if is_sql else _NO_EVENT_FILTER_INSIGHT
    if kind == FindingKind.NO_START_DATE:
        if not is_sql:
            return _NO_START_DATE_INSIGHT
        return _NO_START_DATE_FILTERS if reason == FindingReason.FILTERS else _NO_START_DATE_SQL
    if kind == FindingKind.PERSONS_JOIN:
        return _PERSONS_JOIN
    raise ValueError(f"No copy for finding kind {kind}")


def build_warning(
    *,
    kind: FindingKind,
    query_kind: str,
    measurements: ScanMeasurements,
    reason: FindingReason | None = None,
    evidence: str | None = None,
) -> QueryScanWarning:
    copy = _copy_for(kind, reason, is_sql=query_kind == _SQL_QUERY_KIND)
    return QueryScanWarning(
        kind=kind,
        reason=reason,
        message=f"{copy.lead} {copy.advice}",
        fix=copy.fix,
        evidence=evidence,
        rows_read=measurements.rows_read,
        duration_ms=measurements.duration_ms,
    )


def explain_evidence(
    keys: tuple[str, ...], *, before: int | None, after: int | None, subquery_index: int | None
) -> str:
    """What ClickHouse's deciding index step reported, for the person to check against.

    ``before`` and ``after`` are the granules that step read and kept. ``subquery_index`` is set
    when the finding is about an ``IN`` subquery, so the person can tell which one.
    """
    used = ", ".join(keys) if keys else "no columns"
    if before is None or after is None:
        evidence = f"ClickHouse's index used {used}."
    else:
        evidence = f"ClickHouse's index used {used} and kept {after:,} of {before:,} granules."
    if subquery_index is not None:
        return f"In subquery {subquery_index + 1}: {evidence}"
    return evidence


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
