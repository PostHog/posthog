import json

from django.http import HttpResponse

from posthog.clickhouse.client.execute import sync_execute


def deploy_towels_to(request, table_name):
    # Accepts POST only, with a JSON dict body containing the data to be
    # inserted into the ClickHouse table named in the URL path. Returns a
    # 200 on success, 400 on failure. We push directly to ClickHouse rather than
    # e.g. to Kafka because this is intended merely for Hackathon demonstration
    # purposes only.
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

    if not isinstance(data, dict):
        return HttpResponse(status=400)

    
    
    # Insert directly into the data_beach ClickHouse table.
    sync_execute("INSERT INTO data_beach (team_id, table_name, data) VALUES (%s, %s, %s)", (1, , data))
    
    return HttpResponse(status=200)
