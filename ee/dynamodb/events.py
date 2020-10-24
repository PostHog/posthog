import boto3  # type: ignore

from ee.clickhouse.models.event import delete_event, update_event
from ee.dynamodb.models.events import Event
from posthog.settings import DYNAMODB_URL

DYNAMODB_EVENTS_TABLE = "Events"


def create_events_table(dynamodb=None):
    if not dynamodb:
        dynamodb = boto3.resource("dynamodb", endpoint_url=DYNAMODB_URL, region_name="us-east-1")
    table = dynamodb.create_table(
        TableName=DYNAMODB_EVENTS_TABLE,
        KeySchema=[{"AttributeName": "distinct_id", "KeyType": "HASH"}, {"AttributeName": "uuid", "KeyType": "RANGE"}],
        AttributeDefinitions=[
            {"AttributeName": "distinct_id", "AttributeType": "S"},
            {"AttributeName": "uuid", "AttributeType": "S"},
        ],
        ProvisionedThroughput={"ReadCapacityUnits": 10, "WriteCapacityUnits": 10},
    )
    return table


def destroy_events_table(dynamodb=None):
    if not dynamodb:
        dynamodb = boto3.resource("dynamodb", endpoint_url=DYNAMODB_URL, region_name="us-east-1")
    table = dynamodb.Table(DYNAMODB_EVENTS_TABLE)
    table.delete()


def ensure_events_table(dynamodb=None):
    """
    Drops and then recreates the events table ensuring it is empty
    """
    if not dynamodb:
        dynamodb = boto3.resource("dynamodb", endpoint_url=DYNAMODB_URL, region_name="us-east-1")

    try:
        destroy_events_table(dynamodb)
    except:
        pass

    create_events_table(dynamodb)


def update_event_person(distinct_id: str, person_uuid: str) -> None:
    events = Event.query(distinct_id)
    for event in events:
        delete_event(event)
        event.person_uuid = person_uuid
        event.save()
        update_event(event)
    return
