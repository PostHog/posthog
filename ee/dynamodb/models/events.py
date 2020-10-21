from pynamodb.attributes import JSONAttribute, NumberAttribute, UnicodeAttribute, UTCDateTimeAttribute
from pynamodb.models import Model


class Event(Model):
    """
    Event model that is stored in DynamoDB
    """

    class Meta:
        table_name = "Events"

    uuid = UnicodeAttribute(null=False)
    event = UnicodeAttribute(null=False)
    properties = JSONAttribute(null=True)
    timestamp = UTCDateTimeAttribute(null=False)
    team_id = NumberAttribute(null=False)
    distinct_id = UnicodeAttribute(null=False)
    created_at = UTCDateTimeAttribute(null=False)
    elements_chain = UnicodeAttribute(null=True)
