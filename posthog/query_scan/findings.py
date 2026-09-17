"""Turn an analysis outcome into the warning a person reads, and the prompt the assistant reads.

A finding reads differently for raw SQL than for an insight built from pickers, so the query kind
chooses which wording to use. Within a kind, three facts choose it: the cause, whether the query
reads this much by design, and where the fix goes. The same facts decide whether the finding is
actionable: whether the person can change the query so it reads less and still answers the same
question. A by-design finding stays, worded as an explanation, and is never actionable.
"""

from enum import StrEnum

from posthog.schema import QueryScanFindingKind, QueryScanFixLocation, QueryScanWarning

from posthog.dataclasses import frozen

# Raw SQL gets a clause to add; an insight built from pickers gets the name of its picker.
SQL_QUERY_KIND = "HogQLQuery"

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


class FindingCause(StrEnum):
    """What in the query text kept ClickHouse from narrowing the read, when the analysis could tell.

    The value picks the wording, and it is the label the `query scan analyzed` event and the
    assistant's prompt carry. Nothing a person sees branches on it: surfaces read `actionable`.
    """

    # The event filter is one branch of an OR, so the index cannot use it.
    IN_OR = "in_or"
    # `event` sits inside a function call, which the index cannot see through.
    WRAPPED = "wrapped"
    # The filter only excludes events, which narrows almost nothing.
    NEGATED = "negated"
    # `event` is compared to a column or a subquery, so there is no fixed name to seek on.
    DYNAMIC = "dynamic"
    # The query names events, but ClickHouse reported the filter unused.
    NOT_PRUNED = "not_pruned"
    # A property condition narrows the events where an event name would.
    PROPERTY_FILTER = "property_filter"
    # One read names events, and a larger read beside it, a subquery or CTE, names none.
    HELPER_READ = "helper_read"
    # The query has a start date that ClickHouse could not skip data with.
    BOUND_NOT_USED = "bound_not_used"


# The causes that leave the person a change to make. Every other cause, every by-design finding and
# every finding inside a saved view gets the wording but no "Fix with AI". None is the plain case: a
# missing start date and a persons join each have a fix, and a query with no event condition at
# all depends on the query kind, which `is_actionable` decides.
_FIXABLE_CAUSES: dict[QueryScanFindingKind, frozenset[FindingCause | None]] = {
    QueryScanFindingKind.NO_EVENT_FILTER: frozenset(
        {
            FindingCause.IN_OR,
            FindingCause.WRAPPED,
            FindingCause.NOT_PRUNED,
            FindingCause.PROPERTY_FILTER,
            FindingCause.HELPER_READ,
        }
    ),
    QueryScanFindingKind.NO_START_DATE: frozenset({None, FindingCause.BOUND_NOT_USED}),
    QueryScanFindingKind.PERSONS_JOIN: frozenset({None}),
}

# Fixed on the insight or the dashboard, so the assistant editing the query has nothing to change.
_OUTSIDE_THE_QUERY = frozenset({QueryScanFixLocation.INSIGHT_DATE_RANGE, QueryScanFixLocation.DASHBOARD_DATE_FILTER})


@frozen
class _Copy:
    # `{subject}` is the query, the insight, a subquery of it, or the view it reads.
    lead: str
    advice: str
    fix: str


_NO_EVENT_FILTER_SQL = _Copy(
    lead=(
        "Queries are fastest when they name a fixed set of events. {subject} has no event filter, so it "
        "reads a large share of the events in its date range, which is slow."
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
        "Insights are fastest when they look at a fixed set of events. {subject} looks at all events, so "
        "it reads a large share of the events in its date range, which is slow."
    ),
    advice="Pick specific events if the question is about some of them.",
    fix="Pick the events this insight is about instead of All events.",
)

# A raw SQL query can name events yet leave ClickHouse unable to prune on them. The cause from the
# tree says which shape blocked it, so the copy names that shape and the specific fix.
_NO_EVENT_FILTER_SQL_BY_CAUSE: dict[FindingCause, _Copy] = {
    FindingCause.IN_OR: _Copy(
        lead=(
            "Queries are fastest when they name a fixed set of events. {subject} names events only inside an OR "
            "with another condition, so that filter cannot be used and it still reads a large share of the events "
            "in its date range, which is slow."
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
    FindingCause.WRAPPED: _Copy(
        lead=(
            "Queries are fastest when they compare `event` directly to fixed names. {subject} wraps `event` in a "
            "function, so that filter cannot be used and it still reads a large share of the events in its date "
            "range, which is slow."
        ),
        advice="Compare `event` directly to the names.",
        fix=(
            "The condition applies a function to `event`, which the index cannot see through. Run one query to "
            "learn the exact stored names: `SELECT DISTINCT event FROM events WHERE <the wrapped condition> AND "
            "timestamp >= now() - interval 7 day LIMIT 20`, then compare `event` directly to those names. If the "
            "names could vary over time, say the rewrite may miss older spellings and ask."
        ),
    ),
    FindingCause.NEGATED: _Copy(
        lead=(
            "Queries are fastest when they explicitly enumerate the events they want. {subject} only excludes "
            "events, so that filter cannot be used and it still reads most of the events in its date range, "
            "which is slow."
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
    FindingCause.DYNAMIC: _Copy(
        lead=(
            "Queries are fastest when they compare `event` to fixed names. {subject} compares `event` to another "
            "column or a subquery, so that filter cannot be used and it still reads a large share of the events "
            "in its date range, which is slow."
        ),
        advice="Compare `event` to fixed names.",
        fix=(
            "`event` is compared to another column or expression, so there is no fixed name to prune on. If that "
            "column has few values, run `SELECT DISTINCT <the column> FROM events WHERE timestamp >= now() - "
            "interval 7 day LIMIT 20` and enumerate; otherwise keep the condition and add the time bound."
        ),
    ),
    FindingCause.NOT_PRUNED: _Copy(
        lead=(
            "Queries are fastest when they compare `event` directly to fixed names. {subject} has an event "
            "filter, but it could not be used, so it still read a large share of the events in its date range, "
            "which is slow."
        ),
        advice="Compare `event` directly to fixed names, outside any OR.",
        fix=(
            "The query names events, but the condition sits where ClickHouse cannot apply it to the events read, "
            "after a join, in HAVING, or on a subquery's output. Move it, unchanged, into the WHERE of the events "
            "read."
        ),
    ),
    FindingCause.PROPERTY_FILTER: _Copy(
        lead=(
            "Queries are fastest when they name a fixed set of events. {subject} narrows events by a property "
            "but names no events, so it still reads a large share of the events in its date range, which is slow."
        ),
        advice=(
            "If that property only appears on some events, add `WHERE event IN ('…')` naming them, for example "
            "`$pageview` for a URL or path filter."
        ),
        fix=(
            "The query filters on a property and names no events, so the index cannot prune. Run one query for "
            "which events carry the property: `SELECT event, count() FROM events WHERE <the property condition> "
            "AND timestamp >= now() - interval 7 day GROUP BY event ORDER BY count() DESC LIMIT 20`. If that is a "
            "few events, add `event IN (<those events>)` and say the answer is the same; if the property is on "
            "most events, say an event filter would change the answer and ask which events matter."
        ),
    ),
    FindingCause.HELPER_READ: _Copy(
        lead=(
            "Queries are fastest when every read of the events table names a fixed set of events. {subject} "
            "names events in one place but reads all events in another, a subquery or CTE with no event filter, "
            "and that unfiltered read is the large one, which is slow."
        ),
        advice="Add an event filter, or at least the same start date, to the unfiltered read too.",
        fix=(
            "The query names events in one read of the events table and reads every event in another, a subquery "
            "or CTE with no event condition, and that read is the large one. Add an event filter to the unfiltered "
            "read: the events the other read names when it stands for the same people or sessions, otherwise the "
            "events its own question is about. If nothing says which events, add the same time bound as the main "
            "read and say the answer may change."
        ),
    ),
}

_NO_EVENT_FILTER_INSIGHT_BY_CAUSE: dict[FindingCause, _Copy] = {
    FindingCause.PROPERTY_FILTER: _Copy(
        lead=(
            "Insights are fastest when they look at a fixed set of events. {subject} looks at all events and "
            "filters them by a property, so it still reads a large share of the events in its date range, which "
            "is slow."
        ),
        advice=(
            "Pick the events that carry that property instead of All events, for example `$pageview` for a URL "
            "or path filter."
        ),
        fix=(
            "The insight looks at All events with a property filter. Run one query for which events carry the "
            "property: `SELECT event, count() FROM events WHERE <the property condition> AND timestamp >= now() - "
            "interval 7 day GROUP BY event ORDER BY count() DESC LIMIT 20`. If that is a few events, pick them in "
            "the series and say the answer is the same; otherwise say picking events would change the answer and "
            "ask."
        ),
    ),
}

_ALL_EVENTS_SQL = _Copy(
    lead=(
        "{subject} reads all events by design: the answer is the set of events itself, or a count of people "
        "or sessions over any event, so an event filter would change it. Reading a large share of the events "
        "in its date range is what makes it slow."
    ),
    advice="There is no event filter to add unless the question is about specific events.",
    fix=(
        "The query reads all events by design: it groups by event, counts distinct people or sessions over "
        "any event, or finds each person's last event. An event filter would change the answer, so do not "
        "propose one. If the question could be about specific events, ask which; otherwise leave the event "
        "set alone."
    ),
)

_ALL_EVENTS_INSIGHT = _Copy(
    lead=(
        "{subject} looks at all events by design: the answer is a breakdown by event, or a count of people "
        "or sessions over any event, so picking events would change it. Reading a large share of the events "
        "in its date range is what makes it slow."
    ),
    advice="There are no events to pick unless the question is about specific ones.",
    fix=(
        "The insight breaks down by event or counts people or sessions over all events by design, so picking "
        "events would change the answer. Do not propose one. Ask whether the question is about specific "
        "events; otherwise leave the series on All events."
    ),
)

_NO_START_DATE_SQL = _Copy(
    lead=(
        "Queries are fastest when they start from a recent date. {subject} has no start date, so it reads "
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

# The range a SQL insight takes through `{filters}` has no start date when nobody set one and when
# it is All time, so one wording covers both.
_OPEN_DATE_RANGE_SQL = _Copy(
    lead=(
        "Queries are fastest when they start from a recent date. The date range on this insight or dashboard "
        "has no start date, so {subject_lower} reads all your data back to the beginning, which is slow."
    ),
    advice="Set a date range with a start date on the insight or the dashboard.",
    fix=(
        "The SQL takes its date range from the insight's or dashboard's filters, and that range has no start "
        "date: it is unset or set to All time. Do not edit the SQL; tell the person to set a date range on the "
        "insight or the dashboard."
    ),
)

_DASHBOARD_ALL_TIME_SQL = _Copy(
    lead=(
        "Queries are fastest when they start from a recent date. The dashboard's date filter is set to All "
        "time, so {subject_lower} gets no start date and reads all your data back to the beginning, which is "
        "slow."
    ),
    advice="Change the dashboard's date filter if you only need recent data.",
    fix=(
        "The SQL takes its date range from `{filters}` and the dashboard's date filter is All time. Do not "
        "edit the SQL; tell the person to change the dashboard's date filter."
    ),
)

_BOUND_NOT_USED_SQL = _Copy(
    lead=(
        "Queries are fastest when they start from a fixed recent date. {subject} has a start date, but it "
        "could not be used to skip older data: it compares `timestamp` to another column, wraps it in a "
        "function, or sits where the events read cannot see it, so the query still reads all your data back "
        "to the beginning, which is slow."
    ),
    advice=(
        "Keep it and add a fixed start date directly on the events read, for example "
        "`AND timestamp >= now() - interval 30 day`."
    ),
    fix=(
        "The query bounds `timestamp`, but ClickHouse could not skip data with the bound: it compares to "
        "another column, wraps `timestamp` in a function, or sits in a CTE or subquery the events read does "
        "not see. Keep that condition and add a fixed relative bound beside it on the events read, "
        "`timestamp >= now() - interval N day`, with N from the question or 30 days. Never a calendar date. "
        "No exploration needed."
    ),
)

_ALL_HISTORY_SQL = _Copy(
    lead=(
        "{subject} finds a first event ever, so it reads all your data back to the beginning by design. A "
        "start date would change the answer. Reading everything is what makes it slow."
    ),
    advice="There is no start date to add unless the question only needs recent history.",
    fix=(
        "The query finds a first event ever, with `min` or `argMin` over `timestamp` or a ranking window "
        "ordered by it, and has no lower bound, so it reads all history by design and a start date would "
        "change the answer. Do not propose a time bound for that read. If the question only needs people "
        "first seen recently, ask before changing anything."
    ),
)

_NO_START_DATE_INSIGHT = _Copy(
    lead=(
        "Insights are fastest when they start from a recent date. {subject} has no start date, so it reads "
        "all your data back to the beginning, which is slow."
    ),
    advice="Set a date range if you only need recent data.",
    fix="Set a date range on the insight instead of All time.",
)

_DASHBOARD_ALL_TIME_INSIGHT = _Copy(
    lead=(
        "Insights are fastest when they start from a recent date. The dashboard's date filter is set to All "
        "time, which overrides the date range on {subject_lower}, so it reads all your data back to the "
        "beginning, which is slow."
    ),
    advice="Change the dashboard's date filter if you only need recent data.",
    fix=(
        "The insight's own date range is overridden by the dashboard's date filter, which is All time. Do not "
        "change the insight's date range; tell the person to change the dashboard's date filter."
    ),
)

_ALL_HISTORY_INSIGHT = _Copy(
    lead=(
        "{subject} finds each person's first event, so it reads all your data back to the beginning by "
        "design. A date range would change the answer. Reading everything is what makes it slow."
    ),
    advice="There is no date range to set unless the question only needs recent history.",
    fix=(
        "The insight uses a first-time math or first-time retention, which reads from the project's first "
        "event by design, so a date range would change the answer. Do not propose a date range change."
    ),
)

_PERSONS_JOIN = _Copy(
    lead=(
        "Queries are fastest when they take person details from the events table. {subject} joins the "
        "persons table, and reading it costs about as much as reading the events, which is slow."
    ),
    advice="Read person properties from the events table instead, for example `person.properties.email`.",
    fix=(
        "The query reads the persons table and that read is as large as the events read. If it filters or "
        "selects a person property, use the copy stored on the event (`person.properties.x`) instead of "
        "joining; if the join only resolves identity, drop it. Say what changes. If unsure whether the person "
        "needs current or at-event property values, ask."
    ),
)


def _by_cause(table: dict[FindingCause, _Copy], cause: FindingCause | None, default: _Copy) -> _Copy:
    return default if cause is None else table.get(cause, default)


def _copy_for(
    kind: QueryScanFindingKind,
    cause: FindingCause | None,
    *,
    is_sql: bool,
    by_design: bool,
    fix_location: QueryScanFixLocation,
) -> _Copy:
    if kind == QueryScanFindingKind.NO_EVENT_FILTER:
        if by_design:
            return _ALL_EVENTS_SQL if is_sql else _ALL_EVENTS_INSIGHT
        if not is_sql:
            return _by_cause(_NO_EVENT_FILTER_INSIGHT_BY_CAUSE, cause, _NO_EVENT_FILTER_INSIGHT)
        return _by_cause(_NO_EVENT_FILTER_SQL_BY_CAUSE, cause, _NO_EVENT_FILTER_SQL)
    if kind == QueryScanFindingKind.NO_START_DATE:
        if by_design:
            return _ALL_HISTORY_SQL if is_sql else _ALL_HISTORY_INSIGHT
        if fix_location == QueryScanFixLocation.DASHBOARD_DATE_FILTER:
            return _DASHBOARD_ALL_TIME_SQL if is_sql else _DASHBOARD_ALL_TIME_INSIGHT
        if not is_sql:
            return _NO_START_DATE_INSIGHT
        if fix_location == QueryScanFixLocation.INSIGHT_DATE_RANGE:
            return _OPEN_DATE_RANGE_SQL
        return _BOUND_NOT_USED_SQL if cause == FindingCause.BOUND_NOT_USED else _NO_START_DATE_SQL
    if kind == QueryScanFindingKind.PERSONS_JOIN:
        return _PERSONS_JOIN
    raise ValueError(f"No copy for finding kind {kind}")


def is_actionable(
    kind: QueryScanFindingKind, cause: FindingCause | None, *, is_sql: bool, by_design: bool, in_view: bool
) -> bool:
    """Whether the person can change the query so it reads less and still answers the same question.
    A read inside a saved view is never actionable from the query that uses the view."""
    if by_design or in_view:
        return False
    if kind == QueryScanFindingKind.NO_EVENT_FILTER and cause is None:
        # An insight's All events series is a choice the person made in a picker. A SQL query that
        # names no events may have left them out, and nothing in it tells which, so it is a warning.
        return is_sql
    return cause in _FIXABLE_CAUSES.get(kind, frozenset())


def _read_location(*, subquery_index: int | None, view_name: str | None) -> QueryScanFixLocation:
    if view_name is not None:
        return QueryScanFixLocation.VIEW
    if subquery_index is not None:
        return QueryScanFixLocation.SUBQUERY
    return QueryScanFixLocation.QUERY


def _subject(*, is_sql: bool, subquery_index: int | None, view_name: str | None) -> str:
    """Who the finding is about, so a person with a bounded main query is not told the query has no
    start date when a subquery or a view is the one reading everything."""
    noun = "query" if is_sql else "insight"
    if view_name is not None:
        return f"The view `{view_name}` inside this {noun}"
    if subquery_index is not None:
        return f"Subquery {subquery_index + 1} of this {noun}"
    return f"This {noun}"


def build_warning(
    *,
    kind: QueryScanFindingKind,
    query_kind: str,
    cause: FindingCause | None = None,
    by_design: bool = False,
    fix_location: QueryScanFixLocation | None = None,
    evidence: str | None = None,
    subquery_index: int | None = None,
    view_name: str | None = None,
) -> QueryScanWarning:
    """``fix_location`` is for a fix that goes outside the query text, on the insight's date range or
    the dashboard's date filter. None takes the location from the read: a view, a subquery, or the
    query itself.
    """
    is_sql = query_kind == SQL_QUERY_KIND
    location = fix_location or _read_location(subquery_index=subquery_index, view_name=view_name)
    copy = _copy_for(kind, cause, is_sql=is_sql, by_design=by_design, fix_location=location)
    subject = _subject(is_sql=is_sql, subquery_index=subquery_index, view_name=view_name)
    lead = copy.lead.format(subject=subject, subject_lower=subject[0].lower() + subject[1:])
    advice = copy.advice
    fix = copy.fix
    if view_name is not None:
        advice = f"{advice} The events read is inside the view `{view_name}`, so the change goes in the view."
        fix = (
            f"{fix} The events read is inside the saved view `{view_name}`, and this query does not contain it. "
            "Do not edit this query for it; tell the person the change belongs in the view."
        )
    elif subquery_index is not None:
        fix = (
            f"{fix} This is about subquery {subquery_index + 1}, an `IN (SELECT …)` of the query; change that subquery."
        )
    return QueryScanWarning(
        kind=kind,
        cause=cause.value if cause is not None else None,
        by_design=by_design,
        fix_location=location,
        message=f"{lead} {advice}",
        fix=fix,
        evidence=evidence,
        actionable=is_actionable(kind, cause, is_sql=is_sql, by_design=by_design, in_view=view_name is not None),
    )


def finding_label(finding: QueryScanWarning) -> str:
    """The kind, then whichever of the cause, `by_design` and a fix location other than the query
    apply, joined by `/`. The `query scan analyzed` event splits findings by it, and the job uses
    it to drop a finding that several executions of one run repeat."""
    parts = [str(finding.kind)]
    if finding.cause:
        parts.append(finding.cause)
    if finding.by_design:
        parts.append("by_design")
    if finding.fix_location is not None and finding.fix_location != QueryScanFixLocation.QUERY:
        parts.append(str(finding.fix_location))
    return "/".join(parts)


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


def assistant_prompt(
    findings: list[QueryScanWarning],
    *,
    rows_read: int | None = None,
    duration_ms: int | None = None,
    range_share: float | None = None,
    project_share: float | None = None,
    killed: bool = False,
    fixable_only: bool = False,
) -> str | None:
    """What the assistant reads about a slow run: the goal, the run, one line per finding, and the
    standing rules. "Fix with AI" sends it as the person's message, and the in-app assistant and MCP
    get it above a slow run's results, so all of them read the same text.

    ``fixable_only`` is for "Fix with AI": None unless a finding is actionable, and without the
    findings fixed on the insight or the dashboard rather than in the query. A by-design finding
    stays, because its guidance tells the assistant what not to change.
    """
    if fixable_only:
        if not any(finding.actionable for finding in findings):
            return None
        findings = [
            finding for finding in findings if finding.by_design or finding.fix_location not in _OUTSIDE_THE_QUERY
        ]
    if not findings:
        return None
    lines = [ASSISTANT_GOAL, ""]
    if rows_read is not None and duration_ms is not None:
        lines.append(_run_line(rows_read, duration_ms, killed))
    elif killed:
        lines.append("ClickHouse stopped this query before it finished.")
    if range_share is not None:
        lines.append(f"It read about {round(range_share * 100)}% of the events in this date range.")
    if project_share is not None:
        lines.append(f"It read about {round(project_share * 100)}% of the project's events.")
    lines.extend(_finding_line(finding) for finding in findings)
    lines.extend(["", ASSISTANT_RULES])
    return "\n".join(lines)


def _run_line(rows_read: int, duration_ms: int, killed: bool) -> str:
    rows = format_rows(rows_read)
    seconds = format_seconds(duration_ms)
    if killed:
        return f"ClickHouse stopped this query after {seconds} s, having read {rows} rows."
    return f"This query read {rows} rows in {seconds} s."


def _finding_line(finding: QueryScanWarning) -> str:
    head = f"{finding.kind} ({finding.cause})" if finding.cause else str(finding.kind)
    parts = [f"{head}:"]
    if finding.evidence:
        parts.append(finding.evidence)
    parts.append(finding.fix)
    return "- " + " ".join(parts)


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
