import json

from django.http import HttpResponse, HttpRequest
from django.views.decorators.csrf import csrf_exempt
import pydantic
from posthog.api.utils import get_event_ingestion_context

from posthog.clickhouse.client.execute import sync_execute
from posthog.models.team.team import Team


@csrf_exempt
def deploy_towels_to(request, table_name):
    # Accepts POST only, with a JSON dict body containing the data to be
    # inserted into the ClickHouse table named in the URL path. Returns a
    # 200 on success, 400 on failure. We push directly to ClickHouse rather than
    # e.g. to Kafka because this is intended merely for Hackathon demonstration
    # purposes only.
    #
    # The payload should look like this:
    # {
    #     "id": "some-id",
    #     "token": "some-token",
    #     "data": "{\"some\": \"data\"}"
    # }
    #
    # Note that this is likely a very high volume endpoint, and will be tricky
    # to handle at scale. We may want to consider instead importing from S3 in
    # the background which we would then we more easily ingested as a background
    # process, possibly directly into ClickHouse. This would relieve the client
    # of having to handle e.g. throttling, retries etc.
    if request.method != "POST":
        return HttpResponse(status=405)

    # Try to parse the request as JSON, and check that it's a dict that we'd be
    # able to insert into ClickHouse and query with JSONExtract. We simply put
    # the data as is into the table as the data column, and add team_id and
    # table name as the other columns. We don't do any validation of the data
    # itself, or of the table name. We may want to add some validation of the
    # table data against a schema, but that's not a priority for now.
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError as e:
        return HttpResponse(str(e), status=400)

    try:
        payload = RequestPayload(**data)
    except pydantic.ValidationError as e:
        return HttpResponse(str(e), status=400)

    # Get the team_id from the token in the payload body
    ingestion_context, _, _ = get_event_ingestion_context(request, data, payload.token)

    if ingestion_context is None:
        return HttpResponse(status=403)

    team_id = ingestion_context.team_id

    # Insert directly into the data_beach ClickHouse table.
    sync_execute(
        """
        INSERT INTO data_beach_appendable (
            team_id, 
            table_name, 
            id,
            data
        ) VALUES
    """,
        [(team_id, table_name, payload.id, payload.data)],
    )

    return HttpResponse(status=200)


class RequestPayload(pydantic.BaseModel):
    id: str = pydantic.Field(..., min_length=1)
    token: str = pydantic.Field(..., min_length=1)
    data: str = pydantic.Field(..., min_length=1)


@csrf_exempt
def ship_s3_to_beach(request: HttpRequest, table_name: str):
    """
    Given an S3 pattern, this endpoint will ship the data to ClickHouse using an
    S3 table function. This is intended to enable more scalable imports of data
    into the Data Beach.

    You need to also specify the AWS credentials with read permissions to the
    objects resource. I suspect you also need bucket list permissions as well.

    We associate all the data imported with the team that is associated with the
    provided token.
    """
    if request.method != "POST":
        return HttpResponse(status=405)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return HttpResponse(status=400)

    try:
        payload = ShipS3ToBeachPayload(**data)
    except pydantic.ValidationError:
        return HttpResponse(status=400)

    ingestion_context, _, _ = get_event_ingestion_context(request, data, payload.token)

    if ingestion_context is None:
        return HttpResponse(status=403)

    team_id = ingestion_context.team_id

    # Insert directly into the data_beach ClickHouse table. We expect the data
    # to be in airbyte format, which looks like this:
    # {"_airbyte_ab_id":"88e19437-5ac1-4696-a4bc-8b8acf973838","_airbyte_emitted_at":1680048932176,"_airbyte_data":{...}}
    # We extract the _airbyte_data field and insert that into the
    # data_beach_appendable as the data column, the _airbyte_ab_id as the id

    # NOTE: this is sync atm which isn't going to scale.
    # TODO: return immediately with the query id, then add a status endpoint to
    # monitor it.
    # TODO: don't use ClickHouse s3 function, or at least ensure the ClickHouse
    # cluster that we're querying is isolated from other customers. I suspect
    # that orcestrating outside of ClickHouse would be more maintainable and
    # scaleable here. It's possibly easy to get in to a situation where there
    # are things running in ClickHouse that are tricky to run operationally e.g.
    # needing to pause ingestion, or needing to restart the cluster.
    sync_execute(
        """
        INSERT INTO data_beach_appendable (
            team_id, 
            table_name, 
            id,
            data
        ) SELECT 
            %(team_id)d, 
            %(table_name)s, 
            _airbyte_ab_id,
            toJSONString(_airbyte_data)
        FROM s3(
            %(s3_pattern)s, 
            %(aws_access_key_id)s, 
            %(aws_secret_access_key)s,
            'JSONEachRow' 
        )
    """,
        {
            "team_id": team_id,
            "table_name": table_name,
            "s3_pattern": payload.s3_uri_pattern,
            "aws_access_key_id": payload.aws_access_key_id,
            "aws_secret_access_key": payload.aws_secret_access_key,
        },
    )

    return HttpResponse(status=200)


class ShipS3ToBeachPayload(pydantic.BaseModel):
    token: str = pydantic.Field(..., min_length=1)
    s3_uri_pattern: str = pydantic.Field(..., min_length=1)
    aws_access_key_id: str = pydantic.Field(..., min_length=1)
    aws_secret_access_key: str = pydantic.Field(..., min_length=1)
