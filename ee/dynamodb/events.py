import boto3  # type: ignore

from ee.clickhouse.models.event import delete_event, update_event
from ee.dynamodb.models.events import Event
from posthog.settings import DYNAMODB_URL

DYNAMODB_EVENTS_TABLE = "Events"


def create_events_table(*args, **kwargs):
    Event.create_table(read_capacity_units=1, write_capacity_units=1)
    return


def destroy_events_table():
    Event.delete_table()


def ensure_events_table(*args, **kwargs):
    """
    Drops and then recreates the events table ensuring it is empty
    """
    try:
        destroy_events_table()
    except:
        pass

    create_events_table()


def update_event_person(distinct_id: str, person_uuid: str) -> None:
    events = Event.query(distinct_id)
    for event in events:
        delete_event(event)
        event.person_uuid = person_uuid
        event.save()
        update_event(event)
    return
