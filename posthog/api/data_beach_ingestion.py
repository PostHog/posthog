import json

from django.http import HttpResponse, HttpRequest
from django.views.decorators.csrf import csrf_exempt
import fastavro
import pydantic
from posthog.api.utils import get_event_ingestion_context
from django.conf import settings

from posthog.clickhouse.client.execute import sync_execute
from posthog.models.data_beach.data_beach_field import DataBeachField, DataBeachFieldType
from posthog.models.data_beach.data_beach_table import DataBeachTable
import boto3


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
    print(team_id, table_name, payload.airbyte_data.airbyte_ab_id, json.dumps(payload.airbyte_data.airbyte_data))
    sync_execute(
        """
        INSERT INTO data_beach_appendable (
            team_id, 
            table_name, 
            id,
            data
        ) VALUES
    """,
        [(team_id, table_name, payload.airbyte_data.airbyte_ab_id, json.dumps(payload.airbyte_data.airbyte_data))],
    )

    return HttpResponse(status=200)


class AirByteData(pydantic.BaseModel):
    airbyte_ab_id: str = pydantic.Field(..., min_length=1)
    airbyte_emitted_at: int
    airbyte_data: dict

    class Config:
        fields = {
            "airbyte_ab_id": "_airbyte_ab_id",
            "airbyte_emitted_at": "_airbyte_emitted_at",
            "airbyte_data": "_airbyte_data",
        }


class RequestPayload(pydantic.BaseModel):
    token: str = pydantic.Field(..., min_length=1)
    airbyte_data: AirByteData


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


class ImportFromAirByteRequest(pydantic.BaseModel):
    bucket: str = pydantic.Field(..., min_length=1)
    s3_prefix: str = pydantic.Field(..., min_length=1)
    aws_access_key_id: str = pydantic.Field(..., min_length=1)
    aws_secret_access_key: str = pydantic.Field(..., min_length=1)


def import_from_airbyte_s3_destination(request: HttpRequest, team_id: int):
    """
    Given an S3 prefix that is used to store data from AirByte in the Avro
    format, along with the AWS credentials to access the bucket this endpoint
    should:

        1. Create a `DataBeachTable` for each of the subfolders in the S3
           prefix, appended with the name of the those subfolders in then
           separated by a `_`. For instance, if we have a prefix that contains
           the folder stripe, which then contains subfolders customers, events,
           invoices then it should create a `DataBeachTable` called
           `stripe_customers`, `stripe_events` and `stripe_invoices`.
        2. Parse the schema from the first Airbyte file in each of the leaf
           folders e.g. stripe/customers/<timestamp>.avro and use this to
           specify the Schema of the `DataBeachTable` by adding
           `DataBeachField`s to referencing the corresponding `DataBeachTable`.
        3. Trigger an insert into ClickHouse as with the `import_from_s3`
           endpoint. These are trigger asynchronously using the `async_insert`
           ClickHouse query setting such that the request returns immediately.

    Unlike the other endpoints for data beach, this is intended to be used by
    the frontend, and so we don't need to worry about the ingestion context
    token. Rather we use the team_id from the request.

    TODO: this request could take some time, so it would be better to return
    immediately with an identifier to keep track of the import process, and
    defer the import to a background task. We'd also need add an endpoint to be
    able to retrieve the status of the import given the identifier.
    """
    if request.method != "POST":
        return HttpResponse(status=405)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return HttpResponse(status=400)

    try:
        payload = ImportFromAirByteRequest(**data)
    except pydantic.ValidationError:
        return HttpResponse(status=400)

    # Verify that the user has access to the team_id

    # Fetch the list of all files from S3 below the specified S3 prefix.
    s3_client = boto3.client(
        "s3",
        endpoint_url=settings.OBJECT_STORAGE_ENDPOINT,
        region_name=settings.OBJECT_STORAGE_REGION,
        aws_access_key_id=payload.aws_access_key_id,
        aws_secret_access_key=payload.aws_secret_access_key,
    )

    paginator = s3_client.get_paginator("list_objects_v2")
    response_iterator = paginator.paginate(
        Bucket=payload.bucket,
        Prefix=payload.s3_prefix,
    )

    # We're going to use the files under the S3 prefix to determine the table
    # name and schema. We expect to find a .arvo file in each of the leaf nodes
    # of the S3 prefix. We request each of these Avro files to get both the
    # `namespace` e.g. "stripe" from the `namespace` field in the Avro schema,
    # the record `name` e.g. "customers" from the Avro schema and the
    # schema of the records which we'll determine from the `fields` field in the
    # Avro Schema.
    #
    # We'll then create a `DataBeachTable` for each of these, create
    # `DataBeachField`s for each top level field that has a non-nested type e.g.
    # dicts. We'll then trigger an insert into ClickHouse as with the
    # `import_from_s3` endpoint. These are trigger asynchronously using the
    # `async_insert` ClickHouse query setting such that the request returns
    # immediately.
    # NOTE: handling the inserts async isn't going to be resilient to e.g.
    # ClickHouse restarts, duplicates handling etc. We should probably use
    # something else to handle the orchestration of the inserts in the future
    # but it's fine for demo purposes.
    for page in response_iterator:
        for file in page["Contents"] or []:
            # We're only interested in files that end in .avro
            if not file["Key"].endswith(".avro"):
                continue

            # We're going to use the Avro schema to determine the table name and
            # schema. We expect to find a .arvo file in each of the leaf nodes
            # of the S3 prefix. We request each of these Avro files to get both
            # the `namespace` e.g. "stripe" from the `namespace` field in the
            # Avro schema, the record `name` e.g. "customers" from the Avro
            # schema and the schema of the records which we'll determine from
            # the `fields` field in the Avro Schema.
            #
            # We'll then create a `DataBeachTable` for each of these, create
            # `DataBeachField`s for each top level field that has a non-nested
            # type e.g. dicts. We'll then trigger an insert into ClickHouse as
            # with the `import_from_s3` endpoint. These are trigger
            # asynchronously using the `async_insert` ClickHouse query setting
            # such that the request returns immediately.
            # NOTE: handling the inserts async isn't going to be resilient to
            # e.g. ClickHouse restarts, duplicates handling etc. We should
            # probably use something else to handle the orchestration of the
            # inserts in the future but it's fine for demo purposes.
            file_key = file["Key"]
            s3_client.download_file(
                payload.bucket,
                file_key,
                "/tmp/avro.avro",
            )

            with open("/tmp/avro.avro", "rb") as avro_file:
                reader = fastavro.reader(avro_file)
                schema = reader.writer_schema
                assert schema

                # We expect the namespace to be the name of the service that
                # the data is from e.g. "stripe" and the name to be the name of
                # the table that the data is from e.g. "customers". Note that
                # fastapi will _not_ have namespace in the schema, but it will
                # have set the name to be `namespace.name` e.g.
                # "stripe.customers". We'll replace the '.' with an '_' to
                # create the table name.
                table_name = schema["name"].replace(".", "_")
                table, _ = DataBeachTable.objects.get_or_create(
                    name=table_name,
                    team_id=team_id,
                )

                # We expect the fields to be a list of dicts, each of which
                # contains the name of the field and the type of the field.)
                # Fields should map to those specified by the DataBeachFieldType
                # enum.
                tyoe_mapping = {
                    "string": DataBeachFieldType.String,
                    "long": DataBeachFieldType.Integer,
                }

                field_names = []

                for field in schema["fields"]:
                    # If type is a dict then we skip it as we don't support
                    # nested types.
                    if isinstance(field["type"], dict):
                        continue

                    # Get the type of the field, if it's not in the mapping then
                    # skip it. The Avro sckema supports union types to allow for
                    # nullable fields. We do not support that level of detail.
                    # In these cases the type field is a list of types. We
                    # simply take the first one that isn't null.
                    if isinstance(field["type"], list):
                        field_type = [type_ for type_ in field["type"] if type_ != "null"][0]
                    else:
                        field_type = field["type"]

                    field_type = tyoe_mapping.get(field_type)

                    if not field_type:
                        continue

                    field_names.append(field["name"])

                    DataBeachField.objects.get_or_create(
                        team_id=team_id,
                        table=table,
                        name=field["name"],
                        type=field_type,
                    )

                # Trigger an insert using the Avro records from the file,
                # selecting specifically the fields that we have added the
                # schema for. We insert these fields a JSON string into the data
                # column, and using the _airbyte_ab_id as the id.
                values_to_insert = [
                    (
                        team_id,
                        table_name,
                        str(record["_airbyte_ab_id"]),
                        json.dumps({field_name: record[field_name] for field_name in field_names}),
                    )
                    for record in reader
                    if isinstance(record, dict)
                ]

                sync_execute(
                    """
                    INSERT INTO data_beach_appendable (team_id, table_name, id, data)
                    VALUES
                """,
                    values_to_insert,
                )

    return HttpResponse(status=200)
