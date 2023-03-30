import io
import json
from unittest.mock import ANY
import boto3
import boto3.session
from django.conf import settings
from typing import Any
import uuid
from django.test.client import Client
import fastavro
import pytest
from posthog.api.test.test_organization import create_organization
from posthog.api.test.test_team import create_team
from posthog.api.test.test_user import create_user

from posthog.clickhouse.client.execute import sync_execute
from posthog.models.data_beach.data_beach_table import DataBeachTable


def post_data(client: Client, token: str, table_name: str, data: Any):
    # Make a POST request to the data beach endpoint, using the given token
    # and table name, id, and the given data. We simply pass the token along with
    # the body of the request, along with the id. The data is passed as a string
    # which we attempt to insert into the table with no validation, such that we
    # do not need to spend any time parsing it.
    return client.post(
        f"/ingest/deploy_towels_to/{table_name}/",
        data={"token": token, "airbyte_data": data},
        content_type="application/json",
    )


@pytest.mark.django_db
def test_can_load_data_into_data_breach_table(client: Client):
    organization = create_organization(name="test")
    team = create_team(organization=organization)
    id = uuid.uuid4()
    response = post_data(
        client=client,
        token=team.api_token,
        table_name="stripe_customers",
        data={
            "_airbyte_ab_id": id,
            "_airbyte_emitted_at": 1680048932176,
            "_airbyte_data": {"email": "tim@posthog.com"},
        },
    )

    assert response.status_code == 200, response.content

    # Check that the data is actually in the table
    results = sync_execute(
        f"""
        SELECT * 
        FROM data_beach_appendable
        WHERE table_name = 'stripe_customers' 
            AND team_id = {team.pk}
            AND id = '{id}'
    """
    )

    assert len(results) == 1


@pytest.mark.django_db
def test_get_403_for_invalid_token(client: Client):
    response = post_data(
        client=client,
        token="invalid",
        table_name="stripe_customers",
        data={
            "_airbyte_ab_id": "asdf",
            "_airbyte_emitted_at": 1680048932176,
            "_airbyte_data": {"email": "tim@posthog.com"},
        },
    )

    assert response.status_code == 403


@pytest.mark.django_db
def test_get_400_on_incorrect_input(client: Client):
    organization = create_organization(name="test")
    team = create_team(organization=organization)
    response = post_data(
        client=client,
        token=team.api_token,
        table_name="stripe_customers",
        data={
            "_airbyte_ab_id": "",
            "_airbyte_emitted_at": 1680048932176,
            "_airbyte_data": {"email": "tim@posthog.com"},
        },
    )

    assert response.status_code == 400


@pytest.mark.django_db
def test_gives_405_on_non_post(client: Client):
    response = client.get("/ingest/deploy_towels_to/stripe_customers/")

    assert response.status_code == 405


def trigger_insert_from_s3(
    client: Client, token: str, table_name: str, uri_pattern: str, aws_access_key_id: str, aws_secret_access_key: str
):
    return client.post(
        f"/ingest/deploy_towels_to/{table_name}/import_from_s3",
        data={
            "token": token,
            "aws_access_key_id": aws_access_key_id,
            "aws_secret_access_key": aws_secret_access_key,
            "s3_uri_pattern": uri_pattern,
        },
        content_type="application/json",
    )


@pytest.mark.django_db
def test_can_trigger_insert_from_s3(client: Client):
    """
    Given a jsonl formatted AirByte file in S3, we should be able to trigger an
    insert into the data beach appendable table. We need to specify an S3 uri
    pattern, an access key and a secret. The data should be inserted using the
    team_id that is resolved from the provided token.

    AirByte data looks like this:

      {
        "_airbyte_ab_id":"88e19437-5ac1-4696-a4bc-8b8acf973838",
        "_airbyte_emitted_at":1680048932176,
        "_airbyte_data":{...}
      }

    """
    # First upload a JSONL file of some example data to S3 (minio)
    # We need to make sure we're pointing at minio, so we need to specify the
    # s3_endpoint_url appropriately.
    id = str(uuid.uuid4())
    bucket = str(uuid.uuid4())
    key = "test-prefix/stripe_customers/123.jsonl"
    session = boto3.Session(
        aws_access_key_id=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
        aws_secret_access_key=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
    )
    s3_client = session.client(
        "s3",
        endpoint_url=settings.OBJECT_STORAGE_ENDPOINT,
        region_name=settings.OBJECT_STORAGE_REGION,
        config=boto3.session.Config(signature_version="s3v4"),
    )
    s3_client.create_bucket(Bucket=bucket)

    data = json.dumps(
        {"_airbyte_ab_id": id, "_airbyte_emitted_at": 1680048932176, "_airbyte_data": {"email": "tim@posthog.com"}}
    )
    s3_client.put_object(
        Bucket=bucket,
        Key=key,
        Body=data,
    )

    organization = create_organization(name="test")
    team = create_team(organization=organization)

    response = trigger_insert_from_s3(
        client=client,
        token=team.api_token,
        table_name="stripe_customers",
        # Hack: we need to use object_storage here instead of localhost as the
        # host as ClickHouse is running within the docker compose network and
        # will not be able to resolve localhost to minio.
        uri_pattern=f"http://object-storage:19000/{bucket}/{key}",
        aws_access_key_id=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
        aws_secret_access_key=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
    )

    assert response.status_code == 200

    # Check that the data is actually in the table
    results = sync_execute(
        f"""
        SELECT data
        FROM data_beach_appendable
        WHERE table_name = 'stripe_customers'
            AND team_id = {team.pk}
    """
    )

    assert results == [('{"email":"tim@posthog.com"}',)]


def trigger_import_from_airbyte_s3_destination(
    client: Client, team_id: int, bucket: str, s3_prefix: str, aws_access_key_id: str, aws_secret_access_key: str
):
    return client.post(
        f"/api/projects/{team_id}/import_from_airbyte_s3_destination",
        data={
            "aws_access_key_id": aws_access_key_id,
            "aws_secret_access_key": aws_secret_access_key,
            "bucket": bucket,
            "s3_prefix": s3_prefix,
        },
        content_type="application/json",
    )


def get_data_beach_tables_and_schema_ok(client: Client, project_id: int):
    response = client.get(f"/api/projects/{project_id}/data_beach_tables")
    assert response.status_code == 200
    return response.json()


@pytest.mark.django_db
def test_import_from_airbyte_s3_destination(client: Client):
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

    As the import happens async, we don't check that the data is imported, only
    that the `DataBeachTable`s and `DataBeachField`s are added to the database
    directly.
    """
    # First we push some example stripe Avro data to S3
    id = str(uuid.uuid4())
    bucket = str(uuid.uuid4())
    key = "test-prefix/stripe/customers/123.avro"
    session = boto3.Session(
        aws_access_key_id=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
        aws_secret_access_key=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
    )
    s3_client = session.client(
        "s3",
        endpoint_url=settings.OBJECT_STORAGE_ENDPOINT,
        region_name=settings.OBJECT_STORAGE_REGION,
        config=boto3.session.Config(signature_version="s3v4"),
    )
    s3_client.create_bucket(Bucket=bucket)

    # Generate an Avro string with a schema of two top level fields, one of
    # which is email with type string, the other is account_balance of type
    # long and name of type string.
    avro_file_schema = {
        "type": "record",
        "name": "customers",
        "namespace": "stripe",
        "fields": [
            {"name": "_airbyte_ab_id", "type": {"type": "string", "logicalType": "uuid"}},
            {"name": "_airbyte_emitted_at", "type": {"type": "long", "logicalType": "timestamp-millis"}},
            {"name": "account_balance", "type": ["null", "long"], "default": None},
            {"name": "email", "type": ["null", "string"], "default": None},
            {"name": "name", "type": ["null", "string"], "default": None},
        ],
    }

    # We use the `fastavro` library to generate this schema, as it's the
    # library that Airbyte uses to generate the Avro files.
    avro_file = io.BytesIO()
    fastavro.writer(
        avro_file,
        avro_file_schema,
        [
            {
                "email": "tim@posthog.com",
                "account_balance": 1000,
                "name": "Tim",
                "_airbyte_ab_id": id,
                "_airbyte_emitted_at": 123,
            }
        ],
    )
    avro_file.seek(0)
    s3_client.put_object(
        Bucket=bucket,
        Key=key,
        Body=avro_file,
    )

    organization = create_organization(name="test")
    team = create_team(organization=organization)
    user = create_user(email="tim@posthog.com", organization=organization, password="password123")

    client.force_login(user=user)

    response = trigger_import_from_airbyte_s3_destination(
        client=client,
        team_id=team.pk,
        bucket=bucket,
        s3_prefix=f"test-prefix",
        aws_access_key_id=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
        aws_secret_access_key=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
    )

    assert response.status_code == 200

    tables = get_data_beach_tables_and_schema_ok(client=client, project_id=team.pk)
    assert tables == {
        "count": 1,
        "next": None,
        "previous": None,
        "results": [
            {
                "engine": "appendable",
                "name": "stripe_customers",
                "fields": [
                    {
                        "id": ANY,
                        "name": "account_balance",
                        "type": "Integer",
                    },
                    {
                        "id": ANY,
                        "name": "email",
                        "type": "String",
                    },
                    {
                        "id": ANY,
                        "name": "name",
                        "type": "String",
                    },
                ],
                "id": ANY,
            }
        ],
    }

    # Check that the data is in ClickHouse
    results = sync_execute(
        f"""
            SELECT team_id, table_name, id, data 
            FROM data_beach_appendable
            WHERE id = '{id}'
            AND table_name = 'stripe_customers'
        """
    )

    assert results == [
        (
            team.pk,
            "stripe_customers",
            id,
            '{"account_balance": 1000, "email": "tim@posthog.com", "name": "Tim"}',
        )
    ]

    # Check we can run it again and it doesn't duplicate the data
    response = trigger_import_from_airbyte_s3_destination(
        client=client,
        team_id=team.pk,
        bucket=bucket,
        s3_prefix=f"test-prefix",
        aws_access_key_id=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
        aws_secret_access_key=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
    )

    assert response.status_code == 200

    assert tables == get_data_beach_tables_and_schema_ok(client=client, project_id=team.pk)
