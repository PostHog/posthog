from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime
from typing import Any

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr, parse_select

from posthog.dataclasses import frozen
from posthog.models import Team, User
from posthog.paging import PageRequest

from products.ai_observability.backend.logic.traces.lookback import lookback_selection, seen_before, unscoped_selection
from products.ai_observability.backend.logic.traces.trace_expression_queries import (
    EVENTS_COLUMNS,
    event_anonymous,
    event_has_session,
    event_names_person,
    grouped,
    trace_cost,
)
from products.ai_observability.backend.logic.traces.trace_queries import (
    person_display_name,
    person_display_name_properties,
    read_text,
)
from products.ai_observability.backend.logic.traces.trace_selection import TraceSelection, TraceWindow
from products.ai_observability.backend.logic.traces.trace_selection_queries import (
    execute_selection,
    matching_events_condition,
)

from .people import PeopleCounts, PeopleOrder, PeopleQuery

PEOPLE_SELECTION_QUERY_NAME = "ai_people_selection"
PEOPLE_NAMES_QUERY_NAME = "ai_people_names"
PEOPLE_PERSON_QUERY_NAME = "ai_people_person"
PEOPLE_NEW_COUNT_QUERY_NAME = "ai_people_new_count"


@frozen
class PersonGroupRow:
    person_id: str
    distinct_id: str
    anonymous: bool
    session_count: int
    trace_count: int
    cost: float | None
    first_seen_in_range: datetime
    last_seen: datetime


@frozen
class PeoplePageRows:
    rows: tuple[PersonGroupRow, ...]
    counts: PeopleCounts


def _person_events(team: Team, selection: TraceSelection) -> ast.Expr:
    return ast.And(exprs=[matching_events_condition(team, selection), event_names_person(EVENTS_COLUMNS)])


def _window_people(team: Team, selection: TraceSelection) -> ast.SelectQuery:
    query = parse_select(
        "SELECT person_id FROM events WHERE {person_events}",
        placeholders={"person_events": _person_events(team, unscoped_selection(selection, selection.window))},
    )
    assert isinstance(query, ast.SelectQuery)
    return query


def _in_lookback(window: TraceWindow) -> ast.Expr:
    """Whether an event falls in the lookback before the window, from `seen_before(window)` up to the window's start.
    A person is new when none of their AI events does, so every read that tells new people uses this."""
    # The event condition reads past both lookback bounds by the capture buffer, so the bounds also apply to the time.
    return parse_expr(
        "timestamp >= {checked_from} AND timestamp < {range_start}",
        placeholders={
            "checked_from": ast.Constant(value=seen_before(window)),
            "range_start": ast.Constant(value=window.start),
        },
    )


def _seen_before(team: Team, selection: TraceSelection, people: ast.Expr) -> ast.SelectQuery:
    query = parse_select(
        "SELECT DISTINCT person_id FROM events WHERE {person_events} AND {in_lookback} AND {in_people}",
        placeholders={
            "person_events": _person_events(team, lookback_selection(selection)),
            "in_lookback": _in_lookback(selection.window),
            "in_people": ast.CompareOperation(
                op=ast.CompareOperationOp.GlobalIn, left=ast.Field(chain=["person_id"]), right=people
            ),
        },
    )
    assert isinstance(query, ast.SelectQuery)
    return query


def _contains(text: ast.Expr, search: str) -> ast.Expr:
    return parse_expr(
        "positionCaseInsensitiveUTF8(ifNull({text}, ''), {search}) > 0",
        placeholders={"text": text, "search": ast.Constant(value=search)},
    )


def _person_in(query: str, matches: ast.Expr) -> ast.Expr:
    people = parse_select(query, placeholders={"matches": matches})
    return ast.CompareOperation(op=ast.CompareOperationOp.In, left=ast.Field(chain=["person_id"]), right=people)


def _search_filter(team: Team, selection: TraceSelection, search: str | None) -> ast.Expr:
    term = (search or "").strip()
    if not term:
        return ast.Constant(value=True)
    # Distinct ids come from the window's events rather than the person mapping, which holds no row for a person whose
    # events were captured without person processing.
    return ast.Or(
        exprs=[
            _person_in(
                "SELECT person_id FROM events WHERE {matches}",
                ast.And(
                    exprs=[
                        _person_events(team, unscoped_selection(selection, selection.window)),
                        _contains(ast.Field(chain=["distinct_id"]), term),
                    ]
                ),
            ),
            _person_in(
                "SELECT id FROM persons WHERE {matches}",
                ast.Or(
                    exprs=[
                        _contains(ast.Call(name="toString", args=[ast.Field(chain=["properties", key])]), term)
                        for key in person_display_name_properties(team)
                    ]
                ),
            ),
        ]
    )


def _people(team: Team, selection: TraceSelection, person_search: str | None) -> ast.SelectQuery:
    """One row per person from their AI events in the selection's window that match its filters and scopes, read in
    one pass grouped by person."""
    people = parse_select(
        """
        SELECT
            person_id,
            argMax(distinct_id, tuple(NOT {anonymous_pick}, timestamp, distinct_id)) AS shown_distinct_id,
            countIf(NOT {anonymous}) = 0 AS anonymous,
            uniqExactIf({session_id}, {has_session}) AS session_count,
            uniqExact({trace_id}) AS trace_count,
            {cost} AS cost,
            min(timestamp) AS first_seen_in_range,
            max(timestamp) AS last_seen
        FROM events
        WHERE {person_events} AND timestamp >= {range_start} AND timestamp <= {range_end}
        GROUP BY person_id
        HAVING {search}
        """,
        placeholders={
            "anonymous_pick": event_anonymous(EVENTS_COLUMNS),
            "anonymous": event_anonymous(EVENTS_COLUMNS),
            "session_id": EVENTS_COLUMNS.session_id,
            "has_session": event_has_session(EVENTS_COLUMNS),
            "trace_id": EVENTS_COLUMNS.trace_id,
            "cost": trace_cost(EVENTS_COLUMNS, grouped),
            "person_events": _person_events(team, selection),
            "range_start": ast.Constant(value=selection.window.start),
            "range_end": ast.Constant(value=selection.window.end),
            "search": _search_filter(team, selection, person_search),
        },
    )
    assert isinstance(people, ast.SelectQuery)
    return people


def _new_people(team: Team, selection: TraceSelection, person_search: str | None) -> ast.SelectQuery:
    """The people with whether each is new. The lookback is tested over the grouped people, because ClickHouse runs a
    `GLOBAL` subquery in the select list of an aggregation over the distributed events table once per stage, which
    reads the lookback twice."""
    query = parse_select(
        "SELECT *, {unseen_before} AS is_new FROM {people}",
        placeholders={
            "unseen_before": ast.CompareOperation(
                op=ast.CompareOperationOp.GlobalNotIn,
                left=ast.Field(chain=["person_id"]),
                right=_seen_before(
                    team,
                    selection,
                    _window_people(team, selection)
                    if selection.person_id is None
                    else ast.Constant(value=[selection.person_id]),
                ),
            ),
            "people": _people(team, selection, person_search),
        },
    )
    assert isinstance(query, ast.SelectQuery)
    return query


def _shown(include_anonymous: bool) -> ast.Expr:
    return ast.Constant(value=True) if include_anonymous else parse_expr("NOT anonymous")


def _sort_key(order: PeopleOrder) -> ast.Expr:
    match order:
        case PeopleOrder.LAST_SEEN:
            return parse_expr("tuple(negate(toUnixTimestamp64Milli(last_seen)), toString(person_id))")
        case PeopleOrder.COST:
            return parse_expr("tuple(isNull(cost), negate(ifNull(cost, 0)), toString(person_id))")


def _page_query(team: Team, query: PeopleQuery, page: PageRequest) -> ast.SelectQuery:
    shown = _shown(query.include_anonymous)
    listed = ast.And(exprs=[shown, parse_expr("is_new")]) if query.new_only else shown
    people = (_new_people if query.new_only else _people)(team, query.selection, query.person_search)
    # Every count and the page come from one pass over the grouped people, so a page past the end still counts them.
    page_query = parse_select(
        """
        SELECT
            arraySlice(
                groupArraySortedIf({take})(
                    tuple(
                        {sort_key}, toString(person_id), shown_distinct_id, anonymous, session_count, trace_count,
                        cost, first_seen_in_range, last_seen
                    ),
                    {listed}
                ),
                {first}
            ) AS page,
            countIf({listed}) AS total,
            countIf(anonymous) AS anonymous_total
        FROM {people}
        """,
        placeholders={
            "take": ast.Constant(value=page.offset + page.limit),
            "sort_key": _sort_key(query.order),
            "listed": listed,
            "first": ast.Constant(value=page.offset + 1),
            "people": people,
        },
    )
    assert isinstance(page_query, ast.SelectQuery)
    return page_query


def load_people_page(team: Team, user: User | None, query: PeopleQuery, page: PageRequest) -> PeoplePageRows:
    """One page of the people with an AI event in the selection's window that matches its filters and scopes, in the
    query's order, with the counts of the people the query lists and of the anonymous ones. Only the new people view
    reads the lookback."""
    [[rows, total, anonymous]] = execute_selection(
        team,
        user,
        query.selection,
        _page_query(team, query, page),
        PEOPLE_SELECTION_QUERY_NAME,
        # The new people view is the slower read a person opts into, so it takes the general time limit.
        list_time_limit=not query.new_only,
    )
    return PeoplePageRows(
        rows=tuple(_group_row(row) for _, *row in rows),
        counts=PeopleCounts(total=total, anonymous=anonymous),
    )


def _group_row(values: Sequence[Any]) -> PersonGroupRow:
    (
        person_id,
        distinct_id,
        is_anonymous,
        session_count,
        trace_count,
        cost,
        first_seen_in_range,
        last_seen,
    ) = values
    return PersonGroupRow(
        person_id=str(person_id),
        distinct_id=distinct_id,
        anonymous=bool(is_anonymous),
        session_count=session_count,
        trace_count=trace_count,
        cost=cost,
        first_seen_in_range=first_seen_in_range,
        last_seen=last_seen,
    )


def _person_query(team: Team, selection: TraceSelection) -> ast.SelectQuery:
    query = parse_select(
        """
        SELECT
            toString(person_id), shown_distinct_id, anonymous, session_count, trace_count, cost, first_seen_in_range,
            last_seen
        FROM {people}
        """,
        placeholders={"people": _people(team, selection, None)},
    )
    assert isinstance(query, ast.SelectQuery)
    return query


def load_person(team: Team, user: User | None, selection: TraceSelection, person_id: str) -> PersonGroupRow | None:
    """The row the person has among the people of the selection, read from their own events only, or None when none of
    their events matches it."""
    scoped = replace(selection, person_id=person_id)
    rows = execute_selection(team, user, scoped, _person_query(team, scoped), PEOPLE_PERSON_QUERY_NAME)
    return _group_row(rows[0]) if rows else None


def _new_count_query(
    team: Team, selection: TraceSelection, *, include_anonymous: bool, person_search: str | None
) -> ast.SelectQuery:
    query = parse_select(
        "SELECT countIf({shown} AND is_new) FROM {people}",
        placeholders={"shown": _shown(include_anonymous), "people": _new_people(team, selection, person_search)},
    )
    assert isinstance(query, ast.SelectQuery)
    return query


def load_new_people_count(
    team: Team, user: User | None, selection: TraceSelection, *, include_anonymous: bool, person_search: str | None
) -> int:
    """How many of the people the selection lists have no AI activity in the lookback before its window, under its
    test-account switch only. Loads after the list's rows, so it takes the general time limit."""
    [[count]] = execute_selection(
        team,
        user,
        selection,
        _new_count_query(team, selection, include_anonymous=include_anonymous, person_search=person_search),
        PEOPLE_NEW_COUNT_QUERY_NAME,
        list_time_limit=False,
    )
    return count


def _display_names_query(team: Team, person_ids: Sequence[str]) -> ast.SelectQuery:
    query = parse_select(
        "SELECT id, {display_name} FROM persons WHERE id IN {person_ids}",
        placeholders={"display_name": person_display_name(team), "person_ids": ast.Constant(value=list(person_ids))},
    )
    assert isinstance(query, ast.SelectQuery)
    return query


def load_display_names(
    team: Team, user: User | None, selection: TraceSelection, person_ids: Sequence[str]
) -> dict[str, str]:
    """Each person's display name from the project's display name properties. A person with none, or with no person
    profile, is absent."""
    if not person_ids:
        return {}
    in_window = unscoped_selection(selection, selection.window)
    rows = execute_selection(team, user, in_window, _display_names_query(team, person_ids), PEOPLE_NAMES_QUERY_NAME)
    return {str(person_id): name for person_id, display_name in rows if (name := read_text(display_name))}
