import boto3


def create_events_table(dynamodb=None):
    if not dynamodb:
        dynamodb = boto3.resource("dynamodb", endpoint_url="http://dynamodb:8000", region_name="us-east-1")
    table = dynamodb.create_table(
        TableName="Events",
        KeySchema=[{"AttributeName": "distinct_id", "KeyType": "HASH"}, {"AttributeName": "uuid", "KeyType": "RANGE"}],
        AttributeDefinitions=[
            {"AttributeName": "distinct_id", "AttributeType": "S"},
            {"AttributeName": "uuid", "AttributeType": "S"},
        ],
        ProvisionedThroughput={"ReadCapacityUnits": 10, "WriteCapacityUnits": 10},
    )
    return table


def put_event(event, dynamodb=None):
    if not dynamodb:
        dynamodb = boto3.resource("dynamodb", endpoint_url="http://dynamodb:8000", region_name="us-east-1")

    table = dynamodb.Table("Events")
    response = table.put_item(Item=event)
    return response
