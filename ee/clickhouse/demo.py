import uuid
from typing import Dict, List
from uuid import uuid4

from ee.clickhouse.models.event import create_event
from ee.clickhouse.models.session_recording_event import create_session_recording_event
from posthog.models import EventDefinition, Person, Team


def bulk_create_events(events: List[Dict], **kw):
    for event_data in events:
        create_event(**event_data, **kw, event_uuid=uuid4())  # type: ignore


def bulk_create_session_recording_events(events: List[Dict], **kw):
    for data in events:
        create_session_recording_event(**data, **kw, uuid=uuid4())  # type: ignore


def insert_localdev_data(team_id=1, number=250):
    team = Team.objects.get(id=team_id)

    EventDefinition.objects.get_or_create(team=team, name="step one")
    EventDefinition.objects.get_or_create(team=team, name="step two")
    EventDefinition.objects.get_or_create(team=team, name="step three")
    EventDefinition.objects.get_or_create(team=team, name="step four")
    EventDefinition.objects.get_or_create(team=team, name="step five")

    for i in range(number):
        try:
            Person.objects.create(distinct_ids=[f"user_{i}"], team=team)
        except Exception as e:
            print(str(e))
        create_event(uuid.uuid4(), "step one", team, f"user_{i}", "2021-05-01 00:00:00")
        create_event(uuid.uuid4(), "step two", team, f"user_{i}", "2021-05-03 00:00:00")
        create_event(uuid.uuid4(), "step three", team, f"user_{i}", "2021-05-05 00:00:00")
        create_event(uuid.uuid4(), "step four", team, f"user_{i}", "2021-05-07 00:00:00")
        create_event(uuid.uuid4(), "step five", team, f"user_{i}", "2021-05-09 00:00:00")
