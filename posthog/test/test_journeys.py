import dataclasses
import json
from datetime import datetime
from typing import Any, Dict, List
from uuid import uuid4

from django.utils import timezone

from posthog.client import sync_execute
from posthog.models import Group, Person, PersonDistinctId, Team
from posthog.models.event.sql import EVENTS_DATA_TABLE
from posthog.test.base import _create_event, flush_persons_and_events


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

    def _create_event_from_args(**event):
        return {**event}

    flush_persons_and_events()
    people = {}
    events_to_create = []
    for distinct_id, events in events_by_person.items():
        if create_people:
            people[distinct_id] = update_or_create_person(distinct_ids=[distinct_id], team_id=team.pk)
        else:
            people[distinct_id] = Person.objects.get(
                persondistinctid__distinct_id=distinct_id, persondistinctid__team_id=team.pk
            )

        for event in events:

            # Populate group properties as well
            group_props = {}
            for property_key, value in (event.get("properties") or {}).items():
                if property_key.startswith("$group_"):
                    group_type_index = property_key[-1]
                    try:
                        group = Group.objects.get(team_id=team.pk, group_type_index=group_type_index, group_key=value)
                        group_property_key = f"group{group_type_index}_properties"
                        group_props = {
                            group_property_key: {**group.group_properties, **event.get(group_property_key, {})},
                        }

                    except Group.DoesNotExist:
                        continue

            if "timestamp" not in event:
                event["timestamp"] = datetime.now()

            events_to_create.append(
                _create_event_from_args(
                    team=team,
                    distinct_id=distinct_id,
                    event=event["event"],
                    timestamp=event["timestamp"],
                    properties=event.get("properties", {}),
                    person_id=people[distinct_id].uuid,
                    person_properties=people[distinct_id].properties or {},
                    group0_properties=event.get("group0_properties", {}) or group_props.get("group0_properties", {}),
                    group1_properties=event.get("group1_properties", {}) or group_props.get("group1_properties", {}),
                    group2_properties=event.get("group2_properties", {}) or group_props.get("group2_properties", {}),
                    group3_properties=event.get("group3_properties", {}) or group_props.get("group3_properties", {}),
                    group4_properties=event.get("group4_properties", {}) or group_props.get("group4_properties", {}),
                )
            )

    _create_all_events_raw(events_to_create)

    return people


def _create_all_events_raw(all_events: List[Dict]):
    parsed = ""
    for event in all_events:
        data: Dict[str, Any] = {
            "properties": {},
            "timestamp": timezone.now().strftime("%Y-%m-%d %H:%M:%S.%f"),
            "person_id": str(uuid4()),
            "person_properties": {},
            "group0_properties": {},
            "group1_properties": {},
            "group2_properties": {},
            "group3_properties": {},
            "group4_properties": {},
        }
        data.update(event)
        in_memory_event = InMemoryEvent(**data)
        parsed += f"""
        ('{str(uuid4())}', '{in_memory_event.event}', '{json.dumps(in_memory_event.properties)}', '{in_memory_event.timestamp}', {in_memory_event.team.pk}, '{in_memory_event.distinct_id}', '', '{in_memory_event.person_id}', '{json.dumps(in_memory_event.person_properties)}', '{json.dumps(in_memory_event.group0_properties)}', '{json.dumps(in_memory_event.group1_properties)}', '{json.dumps(in_memory_event.group2_properties)}', '{json.dumps(in_memory_event.group3_properties)}', '{json.dumps(in_memory_event.group4_properties)}', '{timezone.now().strftime("%Y-%m-%d %H:%M:%S.%f")}', now(), 0)
        """

    sync_execute(
        f"""
    INSERT INTO {EVENTS_DATA_TABLE()} (uuid, event, properties, timestamp, team_id, distinct_id, elements_chain, person_id, person_properties, group0_properties, group1_properties, group2_properties, group3_properties, group4_properties, created_at, _timestamp, _offset) VALUES
    {parsed}
    """
    )


def create_all_events(all_events: List[dict]):
    for event in all_events:
        _create_event(**event)


# We collect all events per test into an array and batch create the events to reduce creation time
@dataclasses.dataclass
class InMemoryEvent:
    event: str
    distinct_id: str
    team: Team
    timestamp: str
    properties: Dict
    person_id: str
    person_properties: Dict
    group0_properties: Dict
    group1_properties: Dict
    group2_properties: Dict
    group3_properties: Dict
    group4_properties: Dict


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
