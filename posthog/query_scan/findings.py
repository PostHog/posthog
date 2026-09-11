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

# The goal and standing rules the assistant reads, shared by the `<query_scan_warning>` block and
# mirrored word for word by the frontend "Fix with AI" message in `queryScan.ts`.
ASSISTANT_GOAL = (
    "Help me get what this query is trying to find, as fast as possible. Start by saying in one sentence what "
    "you think the query is trying to find. If you cannot tell, or if a faster version would answer a different "
    "question, ask me before rewriting. Otherwise propose the rewrite."
)

ASSISTANT_RULES = (
    "The events table is sorted by project, day and event name, so a query is fast when it bounds `timestamp` "
    "and names events; property filters and persons joins do not narrow the read. Use relative time bounds, "
    "never a calendar date. Never invent event names, property values or dates; use only names seen in results "
    "or given by the person. Run at most the one exploration query a finding's guidance names, always with a "
    "recent time bound and a LIMIT, and none when the guidance says none. Propose the rewritten query and label "
    "every change as same answer, narrower, or different. When a change would alter the answer and it is unclear "
    "whether that is acceptable, ask instead of choosing."
)


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
        "The query names no events. If its other conditions imply specific events, run one query: "
        "`SELECT event, count() FROM events WHERE <the other conditions> AND timestamp >= now() - interval 7 day "
        "GROUP BY event ORDER BY count() DESC LIMIT 20`, then propose `event IN (...)` with the names seen and "
        "say the result then covers only those. If the query is about the set of events itself, grouping or "
        "counting by event with no other condition, an event filter would change the answer: do not add one, "
        "propose the time bound, and ask which events matter if a narrower question would do."
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
            "The event condition is one branch of an OR, so the index cannot use it. Run one query for what the "
            "other branch matches: `SELECT event, count() FROM events WHERE <the other branch> AND timestamp >= "
            "now() - interval 7 day GROUP BY event ORDER BY count() DESC LIMIT 20`. If that is a few events, "
            "rewrite as `event IN (<the named events>, <those found>)`, keeping the other branch's own condition "
            "where the answer needs it, and say what changes. If it matches most events, an event filter cannot "
            "help; propose the time bound only."
        ),
    ),
    FindingReason.WRAPPED: _Copy(
        lead=(
            "Queries are fastest when they compare `event` directly to fixed names. This query wraps `event` in a "
            "function, so that filter cannot be used and it still reads every event, which is slow."
        ),
        advice="Compare `event` directly to the names.",
        fix=(
            "The condition applies a function to `event`, which the index cannot see through. Run one query to "
            "learn the exact stored names: `SELECT DISTINCT event FROM events WHERE <the wrapped condition> AND "
            "timestamp >= now() - interval 7 day LIMIT 20`, then compare `event` directly to those names. If the "
            "names could vary over time, say the rewrite may miss older spellings and ask."
        ),
    ),
    FindingReason.NEGATED: _Copy(
        lead=(
            "Queries are fastest when they explicitly enumerate the events they want. This query only excludes "
            "events, so that filter cannot be used and it still reads most events, which is slow."
        ),
        advice="Explicitly enumerate the events you want instead.",
        fix=(
            "The filter excludes events, and the index cannot use an exclusion, so it reads everything. "
            'Exploration cannot reveal the intended set, because the query says "everything except". Ask whether '
            "the person can name the events they want. If they can, replace the exclusion with `event IN (...)`; "
            "if they cannot, keep the exclusion and add the time bound. Do not run exploratory queries for this "
            "finding."
        ),
    ),
    FindingReason.DYNAMIC: _Copy(
        lead=(
            "Queries are fastest when they compare `event` to fixed names. This query compares `event` to another "
            "column or a subquery, so that filter cannot be used and it still reads every event, which is slow."
        ),
        advice="Compare `event` to fixed names.",
        fix=(
            "`event` is compared to another column or expression, so there is no fixed name to prune on. If that "
            "column has few values, run `SELECT DISTINCT <the column> FROM events WHERE timestamp >= now() - "
            "interval 7 day LIMIT 20` and enumerate; otherwise keep the condition and add the time bound."
        ),
    ),
    FindingReason.NOT_PRUNED: _Copy(
        lead=(
            "Queries are fastest when they compare `event` directly to fixed names. This query has an event "
            "filter, but it could not be used, so it still read every event, which is slow."
        ),
        advice="Compare `event` directly to fixed names, outside any OR.",
        fix=(
            "The query names events, but the condition sits where ClickHouse cannot apply it to the events read, "
            "after a join, in HAVING, or on a subquery's output. Move it, unchanged, into the WHERE of the events "
            "read."
        ),
    ),
}

_NO_START_DATE_SQL = _Copy(
    lead=(
        "Queries are fastest when they start from a recent date. This query has no start date, so it reads "
        "all your data back to the beginning, which is slow."
    ),
    advice="If you only need recent data, add `timestamp >= now() - interval 30 day` or the range you need.",
    fix=(
        "Add a relative time bound on `timestamp` in the events read, `timestamp >= now() - interval N day`. "
        "Take N from the question if it states a period. If the question implies all history, a lifetime total "
        "or a first-ever date, say the bound would change the answer and ask how far back is needed. Otherwise "
        "propose 30 days and say it can be widened. No exploration needed."
    ),
)

_NO_START_DATE_FILTERS = _Copy(
    lead=(
        "Queries are fastest when they start from a recent date. No date range is set on this insight or "
        "dashboard, so this query reads all your data back to the beginning, which is slow."
    ),
    advice="Set a date range on the insight or the dashboard.",
    fix=(
        "The SQL takes its date range from the insight's or dashboard's filters and none is set. Do not edit "
        "the SQL; tell the person to set a date range on the insight or the dashboard."
    ),
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
        "The query reads the persons table and that read is as large as the events read. If it filters or "
        "selects a person property, use the copy stored on the event (`person.properties.x`) instead of "
        "joining; if the join only resolves identity, drop it. Say what changes. If unsure whether the person "
        "needs current or at-event property values, ask."
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
