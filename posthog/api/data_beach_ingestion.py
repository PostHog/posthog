import json

from django.views.decorators.csrf import csrf_exempt
from django.http import HttpResponse
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
    except json.JSONDecodeError:
        return HttpResponse(status=400)

    try:
        payload = RequestPayload(**data)
    except pydantic.ValidationError:
        return HttpResponse(status=400)

    # Get the team_id from the token in the payload body
    ingestion_context, _, _ = get_event_ingestion_context(request, data, payload.token)

    if ingestion_context is None:
        return HttpResponse(status=403)

    team_id = ingestion_context.team_id

    # Insert directly into the data_beach ClickHouse table.
    sync_execute(
        """
        INSERT INTO data_beach (
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
