"""Turn an analysis outcome into the warning a person reads.

A no-event-filter or no-start-date finding reads differently for raw SQL than for an insight built
from pickers, so the query kind chooses which wording to use.
"""

from posthog.schema import QueryScanFindingKind, QueryScanFindingReason, QueryScanWarning

from posthog.dataclasses import frozen
from posthog.query_scan.flag import DEFAULT_EVENT_RATIO, DEFAULT_PERSONS_RATIO

FindingKind = QueryScanFindingKind
FindingReason = QueryScanFindingReason

# Raw SQL gets a clause to add; an insight built from pickers gets the name of its picker.
_SQL_QUERY_KIND = "HogQLQuery"


@frozen
class ScanThresholds:
    """Ratio gates, filled from the feature flag payload."""

    event_ratio: float = DEFAULT_EVENT_RATIO
    persons_ratio: float = DEFAULT_PERSONS_RATIO


@frozen
class ScanMeasurements:
    # Rows across every table the run read, from the run itself rather than the plan.
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

# A raw SQL query can name events yet leave ClickHouse unable to prune on them. The reason from the
# tree says which shape blocked it, so the copy names that shape and the specific fix.
_NO_EVENT_FILTER_BY_REASON: dict[FindingReason, _Copy] = {
    FindingReason.IN_OR: _Copy(
        lead=(
            "Queries are fastest when they name a fixed set of events. This query names events only inside an OR "
            "with another condition, so that filter cannot be used and it still reads every event, which is slow."
        ),
        advice="Put the event filter outside the OR: `WHERE event IN ('…') AND (… OR …)`.",
        fix=(
            "If every branch of the OR names events, move the event filter out so it stands on its own, and "
            "change nothing else. If moving it would change which rows match, leave the query as it is and "
            "explain that ClickHouse cannot use an event filter inside an OR."
        ),
    ),
    FindingReason.WRAPPED: _Copy(
        lead=(
            "Queries are fastest when they compare `event` directly to fixed names. This query wraps `event` in a "
            "function, so that filter cannot be used and it still reads every event, which is slow."
        ),
        advice="Compare `event` directly to the names.",
        fix=(
            "If the function around `event` does not change which events match, compare `event` directly to "
            "the names and change nothing else. If it does, leave the query as it is and explain that "
            "ClickHouse cannot use an event filter with a function around the column."
        ),
    ),
    FindingReason.NEGATED: _Copy(
        lead=(
            "Queries are fastest when they explicitly enumerate the events they want. This query only excludes "
            "events, so that filter cannot be used and it still reads most events, which is slow."
        ),
        advice="Explicitly enumerate the events you want instead.",
        fix=(
            "If the events to keep can be named, replace the exclusion with a filter that names them, and "
            "change nothing else. If they cannot, leave the query as it is and explain that ClickHouse "
            "cannot use an event filter that excludes events."
        ),
    ),
    FindingReason.DYNAMIC: _Copy(
        lead=(
            "Queries are fastest when they compare `event` to fixed names. This query compares `event` to another "
            "column or a subquery, so that filter cannot be used and it still reads every event, which is slow."
        ),
        advice="Compare `event` to fixed names.",
        fix=(
            "If the column or subquery stands for a fixed set of event names, compare `event` to those names "
            "and change nothing else. If it does not, leave the query as it is and explain that ClickHouse "
            "cannot use an event filter that compares `event` to data."
        ),
    ),
    FindingReason.NOT_PRUNED: _Copy(
        lead=(
            "Queries are fastest when they compare `event` directly to fixed names. This query has an event "
            "filter, but it could not be used, so it still read every event, which is slow."
        ),
        advice="Compare `event` directly to fixed names, outside any OR.",
        fix="Compare `event` directly to fixed event names, outside any OR. Change nothing else.",
    ),
}

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
        if not is_sql:
            return _NO_EVENT_FILTER_INSIGHT
        return _NO_EVENT_FILTER_BY_REASON.get(reason, _NO_EVENT_FILTER_SQL) if reason else _NO_EVENT_FILTER_SQL
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
    """What the deciding index step reported, for the person to check. ``before`` and ``after`` are
    the granules it read and kept; ``subquery_index`` says which ``IN`` subquery, when it is one.
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
