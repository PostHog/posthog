import os
import json
import dataclasses
from datetime import datetime
from hashlib import md5
from typing import Any
from uuid import UUID, uuid4

from posthog.test.base import _create_event, flush_persons_and_events

from django.utils import timezone

from posthog.clickhouse.client import sync_execute
from posthog.models import Group, Person, PersonDistinctId, Team
from posthog.models.event.sql import EVENTS_DATA_TABLE


def journeys_for(
    events_by_person: dict[str, list[dict[str, Any]]],
    team: Team,
    create_people: bool = True,
) -> dict[str, Person]:
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
            # Create the person UUID from the distinct ID and test path, so that SQL snapshots are deterministic
            derived_uuid = UUID(
                bytes=md5((os.getenv("PYTEST_CURRENT_TEST", "some_test") + distinct_id).encode("utf-8")).digest()
            )
            people[distinct_id] = update_or_create_person(
                distinct_ids=[distinct_id], team_id=team.pk, uuid=derived_uuid
            )
        else:
            people[distinct_id] = Person.objects.get(
                persondistinctid__distinct_id=distinct_id,
                persondistinctid__team_id=team.pk,
            )

        for event in events:
            # Populate group properties as well
            group_mapping = {}
            for property_key, value in (event.get("properties") or {}).items():
                if property_key.startswith("$group_"):
                    group_type_index = property_key[-1]
                    try:
                        group = Group.objects.get(
                            team_id=team.pk,
                            group_type_index=group_type_index,
                            group_key=value,
                        )
                        group_mapping[f"group{group_type_index}"] = group

                    except Group.DoesNotExist:
                        continue

            if "timestamp" not in event:
                event["timestamp"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")

            events_to_create.append(
                {
                    "event_uuid": UUID(event["event_uuid"]) if "event_uuid" in event else uuid4(),
                    "team": team,
                    "distinct_id": distinct_id,
                    "event": event["event"],
                    "timestamp": event["timestamp"],
                    "properties": event.get("properties", {}),
                    "person_id": people[distinct_id].uuid,
                    "person_properties": people[distinct_id].properties or {},
                    "person_created_at": people[distinct_id].created_at,
                    "group0_properties": event.get("group0_properties", {})
                    or getattr(group_mapping.get("group0", {}), "group_properties", {}),
                    "group1_properties": event.get("group1_properties", {})
                    or getattr(group_mapping.get("group1", {}), "group_properties", {}),
                    "group2_properties": event.get("group2_properties", {})
                    or getattr(group_mapping.get("group2", {}), "group_properties", {}),
                    "group3_properties": event.get("group3_properties", {})
                    or getattr(group_mapping.get("group3", {}), "group_properties", {}),
                    "group4_properties": event.get("group4_properties", {})
                    or getattr(group_mapping.get("group4", {}), "group_properties", {}),
                    "group0_created_at": event.get("group0_created_at")
                    or getattr(group_mapping.get("group0", {}), "created_at", None),
                    "group1_created_at": event.get("group1_created_at")
                    or getattr(group_mapping.get("group1", {}), "created_at", None),
                    "group2_created_at": event.get("group2_created_at")
                    or getattr(group_mapping.get("group2", {}), "created_at", None),
                    "group3_created_at": event.get("group3_created_at")
                    or getattr(group_mapping.get("group3", {}), "created_at", None),
                    "group4_created_at": event.get("group4_created_at")
                    or getattr(group_mapping.get("group4", {}), "created_at", None),
                }
            )

    _create_all_events_raw(events_to_create)

    return people


def _create_all_events_raw(all_events: list[dict]):
    parsed = ""
    for event in all_events:
        timestamp = timezone.now()
        data: dict[str, Any] = {
            "properties": {},
            "timestamp": timestamp.strftime("%Y-%m-%d %H:%M:%S.%f"),
            "person_id": str(uuid4()),
            "person_properties": {},
            "group0_properties": {},
            "group1_properties": {},
            "group2_properties": {},
            "group3_properties": {},
            "group4_properties": {},
            "person_created_at": timestamp,
            "group0_created_at": timestamp,
            "group1_created_at": timestamp,
            "group2_created_at": timestamp,
            "group3_created_at": timestamp,
            "group4_created_at": timestamp,
        }
        data.update(event)

        # Remove nulls from created_at
        for key in [
            "person_created_at",
            "group0_created_at",
            "group1_created_at",
            "group2_created_at",
            "group3_created_at",
            "group4_created_at",
        ]:
            if not data[key]:
                data[key] = timestamp
        in_memory_event = InMemoryEvent(**data)
        parsed += f"""
        ('{in_memory_event.event_uuid}', '{in_memory_event.event}', '{json.dumps(in_memory_event.properties)}', '{in_memory_event.timestamp}', {in_memory_event.team.pk}, '{in_memory_event.distinct_id}', '', '{in_memory_event.person_id}', '{json.dumps(in_memory_event.person_properties)}', '{in_memory_event.person_created_at.strftime("%Y-%m-%d %H:%M:%S.%f")}', '{json.dumps(in_memory_event.group0_properties)}', '{json.dumps(in_memory_event.group1_properties)}', '{json.dumps(in_memory_event.group2_properties)}', '{json.dumps(in_memory_event.group3_properties)}', '{json.dumps(in_memory_event.group4_properties)}', '{in_memory_event.group0_created_at.strftime("%Y-%m-%d %H:%M:%S.%f")}', '{in_memory_event.group1_created_at.strftime("%Y-%m-%d %H:%M:%S.%f")}', '{in_memory_event.group2_created_at.strftime("%Y-%m-%d %H:%M:%S.%f")}', '{in_memory_event.group3_created_at.strftime("%Y-%m-%d %H:%M:%S.%f")}', '{in_memory_event.group4_created_at.strftime("%Y-%m-%d %H:%M:%S.%f")}', '{timezone.now().strftime("%Y-%m-%d %H:%M:%S.%f")}', now(), 0)
        """

    sync_execute(
        f"""
    INSERT INTO {EVENTS_DATA_TABLE()} (uuid, event, properties, timestamp, team_id, distinct_id, elements_chain, person_id, person_properties, person_created_at, group0_properties, group1_properties, group2_properties, group3_properties, group4_properties, group0_created_at, group1_created_at, group2_created_at, group3_created_at, group4_created_at, created_at, _timestamp, _offset) VALUES
    {parsed}
    """
    )


def create_all_events(all_events: list[dict]):
    for event in all_events:
        _create_event(**event)


# We collect all events per test into an array and batch create the events to reduce creation time
@dataclasses.dataclass(kw_only=True)
class InMemoryEvent:
    event_uuid: UUID = dataclasses.field(default_factory=uuid4)
    event: str
    distinct_id: str
    team: Team
    timestamp: str
    properties: dict
    person_id: str
    person_created_at: datetime
    person_properties: dict
    group0_properties: dict
    group1_properties: dict
    group2_properties: dict
    group3_properties: dict
    group4_properties: dict
    group0_created_at: datetime
    group1_created_at: datetime
    group2_created_at: datetime
    group3_created_at: datetime
    group4_created_at: datetime


def update_or_create_person(distinct_ids: list[str], team_id: int, **kwargs):
    (person, _) = Person.objects.update_or_create(
        persondistinctid__distinct_id__in=distinct_ids,
        persondistinctid__team_id=team_id,
        defaults={**kwargs, "team_id": team_id},
    )
    for distinct_id in distinct_ids:
        PersonDistinctId.objects.update_or_create(
            distinct_id=distinct_id,
            team_id=person.team_id,
            defaults={
                "person_id": person.id,
                "team_id": team_id,
                "distinct_id": distinct_id,
            },
        )
    return person
