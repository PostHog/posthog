from collections.abc import Callable, Sequence

from posthog.models import Team, User
from posthog.paging import PageRequest

from ..logic.people.people import (
    PeopleOrder as PeopleOrder,
    PeopleQuery as PeopleQuery,
    PeopleView as PeopleView,
    listed_person_label,
    needs_identification,
)
from ..logic.people.people_queries import (
    PersonFirstSeenRow,
    PersonGroupRow,
    load_display_names,
    load_new_people_count,
    load_people_first_seen as read_people_first_seen,
    load_people_page,
    load_person,
)
from ..logic.traces.lookback import (
    LOOKBACK as LOOKBACK,
    seen_before,
)
from ..logic.traces.trace_selection import TraceSelection
from . import people_contracts as contracts
from .contracts import TracePerson


def load_people_list(
    team: Team, user: User | None, query: PeopleQuery, page: PageRequest
) -> Callable[[], contracts.PersonPage]:
    """Loads a page of the people with AI events in the selection, then the display name of each, and returns the step
    that builds the page. The step runs no query, so a caller holding a query concurrency slot can release it first."""
    rows = load_people_page(team, user, query, page)
    names = load_display_names(team, user, query.selection, [row.person_id for row in rows.rows])
    return lambda: contracts.PersonPage(
        count=rows.counts.total,
        results=[_to_item(row, names.get(row.person_id)) for row in rows.rows],
        counts=contracts.PersonListCounts(anonymous=rows.counts.anonymous),
        lookback_days=LOOKBACK.days,
        needs_identification=needs_identification(rows.counts, query),
    )


def get_person(
    team: Team, user: User | None, selection: TraceSelection, person_id: str
) -> contracts.PersonListItem | None:
    """The person's row as the people list of the selection shows it, anonymous or not, or None when none of their
    events matches the selection."""
    row = load_person(team, user, selection, person_id)
    if row is None:
        return None
    return _to_item(row, load_display_names(team, user, selection, [person_id]).get(person_id))


def _to_item(row: PersonGroupRow, display_name: str | None) -> contracts.PersonListItem:
    label = listed_person_label(anonymous=row.anonymous, distinct_id=row.distinct_id, display_name=display_name)
    return contracts.PersonListItem(
        id=row.person_id,
        person=TracePerson(distinct_id=row.distinct_id, label=label),
        anonymous=row.anonymous,
        session_count=row.session_count,
        trace_count=row.trace_count,
        cost=row.cost,
        first_seen_in_range=row.first_seen_in_range,
        last_seen=row.last_seen,
    )


def load_people_new_count(
    team: Team, user: User | None, selection: TraceSelection, *, include_anonymous: bool, person_search: str | None
) -> contracts.PeopleNewCount:
    """How many of the people the list of the selection shows are new to the project's AI, read apart from the list
    because only this read and the new people view read the lookback."""
    return contracts.PeopleNewCount(
        count=load_new_people_count(
            team, user, selection, include_anonymous=include_anonymous, person_search=person_search
        )
    )


def load_people_first_seen(
    team: Team, user: User | None, selection: TraceSelection, person_ids: Sequence[str]
) -> contracts.PersonFirstSeenList:
    """When each requested person was first seen, from the lookback bound to the end of the selection's window. Items
    come back once per id, in the order first requested."""
    first_seen = read_people_first_seen(team, user, selection, person_ids)
    return contracts.PersonFirstSeenList(
        items=[_first_seen_item(person_id, first_seen.get(person_id)) for person_id in dict.fromkeys(person_ids)],
        checked_from=seen_before(selection.window).date(),
    )


def _first_seen_item(person_id: str, row: PersonFirstSeenRow | None) -> contracts.PersonFirstSeen:
    # A person with no AI event from the lookback bound on has none in the lookback either, so they are new.
    if row is None:
        return contracts.PersonFirstSeen(person_id=person_id, first_seen=None, is_new=True)
    return contracts.PersonFirstSeen(person_id=person_id, first_seen=row.first_seen, is_new=row.is_new)
