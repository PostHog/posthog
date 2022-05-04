import dataclasses
import json
from datetime import datetime
from typing import Any, Dict, List
from uuid import uuid4

from django.utils import timezone

from ee.clickhouse.sql.events import EVENTS_DATA_TABLE
from posthog.client import sync_execute
from posthog.models import Person, PersonDistinctId, Team
from posthog.test.base import flush_persons_and_events


def journeys_for(
    events_by_person: Dict[str, List[Dict[str, Any]]], team: Team, create_people: bool = True
) -> Dict[str, Person]:
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

    flush_persons_and_events()
    people = {}
    events_to_create = []
    for distinct_id, events in events_by_person.items():
        if create_people:
            people[distinct_id] = update_or_create_person(distinct_ids=[distinct_id], team_id=team.pk)

        for event in events:
            if "timestamp" not in event:
                event["timestamp"] = datetime.now()

            events_to_create.append(
                _create_event(
                    team=team,
                    distinct_id=distinct_id,
                    event=event["event"],
                    timestamp=event["timestamp"],
                    properties=event.get("properties", {}),
                )
            )

    _create_all_events(events_to_create)

    return people


def _create_all_events(all_events: List[Dict]):
    parsed = ""
    for event in all_events:
        data: Dict[str, Any] = {"properties": {}, "timestamp": timezone.now().strftime("%Y-%m-%d %H:%M:%S.%f")}
        data.update(event)
        in_memory_event = InMemoryEvent(**data)
        parsed += f"""
        ('{str(uuid4())}', '{in_memory_event.event}', '{json.dumps(in_memory_event.properties)}', '{in_memory_event.timestamp}', {in_memory_event.team.pk}, '{in_memory_event.distinct_id}', '', '{timezone.now().strftime("%Y-%m-%d %H:%M:%S.%f")}', now(), 0)
        """

    sync_execute(
        f"""
    INSERT INTO {EVENTS_DATA_TABLE()} (uuid, event, properties, timestamp, team_id, distinct_id, elements_chain, created_at, _timestamp, _offset) VALUES
    {parsed}
    """
    )


# We collect all events per test into an array and batch create the events to reduce creation time
@dataclasses.dataclass
class InMemoryEvent:
    event: str
    distinct_id: str
    team: Team
    timestamp: str
    properties: Dict


def _create_event(**event):
    return {**event}


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
