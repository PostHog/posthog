import json
import boto3
import boto3.session
from django.conf import settings
from typing import Any
import uuid
from django.test.client import Client
import pytest
from posthog.api.test.test_organization import create_organization
from posthog.api.test.test_team import create_team

from posthog.clickhouse.client.execute import sync_execute


def post_data(client: Client, token: str, table_name: str, id: str, data: Any):
    # Make a POST request to the data beach endpoint, using the given token
    # and table name, id, and the given data. We simply pass the token along with
    # the body of the request, along with the id. The data is passed as a string
    # which we attempt to insert into the table with no validation, such that we
    # do not need to spend any time parsing it.
    return client.post(
        f"/ingest/deploy_towels_to/{table_name}/",
        data={"id": id, "token": token, "data": json.dumps(data)},
        content_type="application/json",
    )


@pytest.mark.django_db
def test_can_load_data_into_data_breach_table(client: Client):
    organization = create_organization(name="test")
    team = create_team(organization=organization)
    id = uuid.uuid4()
    response = post_data(
        client=client, token=team.api_token, table_name="stripe_customers", id=id, data={"email": "tim@posthog.com"}
    )

    assert response.status_code == 200

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
        client=client, token="invalid", table_name="stripe_customers", id="some-id", data={"email": "tim@posthog.com"}
    )

    assert response.status_code == 403


@pytest.mark.django_db
def test_get_400_on_incorrect_input(client: Client):
    organization = create_organization(name="test")
    team = create_team(organization=organization)
    response = post_data(
        client=client, token=team.api_token, table_name="stripe_customers", id="", data={"email": "tim@posthog.com"}
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
