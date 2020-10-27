import boto3  # type: ignore

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
