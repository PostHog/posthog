from typing import Any, Dict, List
from uuid import uuid4

from ee.clickhouse.models.event import create_event
from posthog.models import Person, PersonDistinctId, Team


def journeys_for(events_by_person: Dict[str, List[Dict[str, Any]]], team: Team) -> Dict[str, Person]:
    """
    Helper for creating specific events for a team.

    Allows tests to be written in a declarative style

    # these things happened in the past for these people
    events_by_person = {
        "person1": [{"some": "events}],
        "person2": [{"some": "more events}],
    }
    journeys_for(events_by_person, team)

    # then the application receives them
    actual = system_under_test.runs()

    # and we can assert on the results of that
    ...

    Writing tests in this way reduces duplication in test setup
    And clarifies the preconditions of the test
    """

    people = {}
    for distinct_id, events in events_by_person.items():
        people[distinct_id] = update_or_create_person(distinct_ids=[distinct_id], team_id=team.pk)
        for event in events:
            _create_event(
                team=team,
                distinct_id=distinct_id,
                event=event["event"],
                timestamp=event["timestamp"],
                properties=event.get("properties", {}),
            )

    return people


def _create_event(**kwargs):
    kwargs.update({"event_uuid": uuid4()})
    create_event(**kwargs)


def update_or_create_person(distinct_ids: List[str], team_id: int, **kwargs):
    (person, _) = Person.objects.update_or_create(
        persondistinctid__distinct_id__in=distinct_ids,
        persondistinctid__team_id=team_id,
        defaults={**kwargs, "team_id": team_id},
    )
    for distinct_id in distinct_ids:
        PersonDistinctId.objects.update_or_create(
            distinct_id=distinct_id,
            team_id=person.team_id,
            defaults={"person_id": person.id, "team_id": team_id, "distinct_id": distinct_id},
        )
    return person
