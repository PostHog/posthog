from posthog.dataclasses import frozen
from posthog.enums import LabeledStrEnum

from products.ai_observability.backend.logic.traces.trace_selection import TraceSelection

ANONYMOUS_ID_LENGTH = 8


class PeopleOrder(LabeledStrEnum):
    LAST_SEEN = "last_seen", "Last seen"
    COST = "cost"


class PeopleView(LabeledStrEnum):
    NEW = "new"


@frozen
class PeopleQuery:
    selection: TraceSelection
    order: PeopleOrder
    include_anonymous: bool
    new_only: bool
    person_search: str | None


@frozen
class PeopleCounts:
    total: int
    anonymous: int


def _narrowed(query: PeopleQuery) -> bool:
    return (
        query.new_only
        or bool((query.person_search or "").strip())
        or query.selection.narrowed
        or query.selection.session_id is not None
    )


def needs_identification(counts: PeopleCounts, query: PeopleQuery) -> bool:
    """Whether the people in range are all anonymous, so a list that hides them shows nobody until users are
    identified. Only an unnarrowed list can show that: a person search, the new people view, a scope or a property
    filter that finds only anonymous people found no match instead. The date range and the test-account switch do not
    narrow it."""
    return not query.include_anonymous and not _narrowed(query) and counts.total == 0 and counts.anonymous > 0


def listed_person_label(*, anonymous: bool, distinct_id: str, display_name: str | None) -> str:
    """The name a listed person goes by: Anonymous and the start of their distinct id when they are anonymous in the
    selection, else their display name, else their distinct id."""
    if anonymous:
        return f"Anonymous {distinct_id[:ANONYMOUS_ID_LENGTH]}"
    return display_name or distinct_id
