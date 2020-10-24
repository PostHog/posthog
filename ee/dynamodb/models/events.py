from pynamodb.attributes import JSONAttribute, NumberAttribute, UnicodeAttribute, UTCDateTimeAttribute
from pynamodb.models import Model

from posthog import settings


class Event(Model):
    """
    Event model that is stored in DynamoDB
    """

    class Meta:
        table_name = "Events"
        if settings.DEBUG:
            host = settings.DYNAMODB_URL

    uuid = UnicodeAttribute(range_key=True)
    event = UnicodeAttribute(null=False)
    properties = JSONAttribute(null=True)
    timestamp = UTCDateTimeAttribute(null=False)
    team_id = NumberAttribute(null=False)
    distinct_id = UnicodeAttribute(hash_key=True)
    created_at = UTCDateTimeAttribute(null=False)
    elements_chain = UnicodeAttribute(null=True)
    person_uuid = UnicodeAttribute(null=True)
