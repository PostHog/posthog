from datetime import datetime

from pydantic import Field

from ..logic.people.people import ANONYMOUS_ID_LENGTH
from ..logic.traces.lookback import LOOKBACK
from .contracts import Contract, TracePerson


class PersonListItem(Contract):
    """A person with AI events in range. Every field reads only their events in range that match the property filters
    and scopes. Whether they are new comes from the first seen sub-resource."""

    id: str = Field(description="The person's UUID.")
    person: TracePerson = Field(
        description="The latest identified distinct id among the person's events in range, or their latest anonymous "
        "one when they are anonymous, labeled by the project's display name properties, else by the distinct id. An "
        f"anonymous person is labeled Anonymous and the first {ANONYMOUS_ID_LENGTH} characters of their distinct id."
    )
    anonymous: bool = Field(
        description="Whether every event of the person in range has the trace id as its distinct id, which is what an "
        "SDK sends when no user was identified."
    )
    session_count: int = Field(description="How many sessions the person's events in range carry.")
    trace_count: int = Field(description="How many traces have an event of the person in range.")
    cost: float | None = Field(
        description="The summed cost in USD of the person's own events in range. A trace shared with other people adds "
        "only the person's events. Null when none of their events reports a cost."
    )
    first_seen_in_range: datetime = Field(description="The time of the person's earliest event in range.")
    last_seen: datetime = Field(description="The time of the person's latest event in range.")


class PersonListCounts(Contract):
    anonymous: int = Field(description="How many people in range are anonymous, whether or not they are listed.")


class PersonPage(Contract):
    count: int = Field(description="How many people the list holds across every page, only new ones in the new view.")
    results: list[PersonListItem] = Field(description="A page of people in the requested order.")
    counts: PersonListCounts = Field(
        description="How many people in range are anonymous, the same on every page and in the new people view. The "
        "number of new people is its own sub-resource, because only it and the new people view read the lookback."
    )
    lookback_days: int = Field(
        description="How many days before the range starts a person's AI activity makes them not new, the same for "
        "the new people view and the new people count."
    )
    needs_identification: bool = Field(
        description="Whether the people in range are all anonymous, so hiding anonymous people lists nobody until "
        "users are identified. False while a person search, the new people view, a scope or a property filter narrows "
        "the list."
    )


class PeopleNewCount(Contract):
    count: int = Field(
        description=f"How many of the people the list shows have no AI activity in the {LOOKBACK.days} days before the "
        "range starts, under the test-account filter only. The new people view lists them."
    )


class PersonList(PersonPage):
    next: str | None = Field(description="URL of the next page, or null on the last page.")
    previous: str | None = Field(description="URL of the previous page, or null on the first page.")
