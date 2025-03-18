import functools
import uuid

import aioboto3
import pytest
import pytest_asyncio
from django.conf import settings
from django.test.client import Client as HttpClient
from rest_framework import status

from posthog.api.test.batch_exports.conftest import start_test_worker
from posthog.api.test.batch_exports.fixtures import create_organization
from posthog.api.test.batch_exports.operations import (
    create_batch_export_ok,
)
from posthog.api.test.test_team import create_team
from posthog.api.test.test_user import create_user

pytestmark = [
    pytest.mark.django_db,
]


@pytest.mark.parametrize("destination", ["S3", "BigQuery", "Snowflake"])
def test_can_get_test_for_destination(client: HttpClient, destination: str):
    organization = create_organization("Test Org")
    team = create_team(organization)
    user = create_user("test@user.com", "Test User", organization)
    client.force_login(user)

    response = client.get(
        f"/api/projects/{team.pk}/batch_exports/test",
        {"destination": destination},
        content_type="application/json",
    )

    assert response.status_code == status.HTTP_200_OK, response.json()

    destination_test = response.json()

    assert "steps" in destination_test
    assert isinstance(destination_test["steps"], list)
    assert len(destination_test["steps"]) > 0
    assert all("name" in step and "description" in step for step in destination_test["steps"])


TEST_ROOT_BUCKET = "test-destination-tests"
SESSION = aioboto3.Session()
create_test_client = functools.partial(SESSION.client, endpoint_url=settings.OBJECT_STORAGE_ENDPOINT)


@pytest.fixture
def bucket_name(request) -> str:
    """Name for a test S3 bucket."""
    try:
        return request.param
    except AttributeError:
        return f"{TEST_ROOT_BUCKET}-{str(uuid.uuid4())}"


@pytest_asyncio.fixture
async def minio_client(bucket_name):
    """Manage an S3 client to interact with a MinIO bucket.

    Yields the client after creating a bucket. Upon resuming, we delete
    the contents and the bucket itself.
    """
    async with create_test_client(
        "s3",
        aws_access_key_id="object_storage_root_user",
        aws_secret_access_key="object_storage_root_password",
    ) as minio_client:
        await minio_client.create_bucket(Bucket=bucket_name)

        yield minio_client

        await delete_all_from_s3(minio_client, bucket_name, key_prefix="/")

        await minio_client.delete_bucket(Bucket=bucket_name)


async def delete_all_from_s3(minio_client, bucket_name: str, key_prefix: str):
    """Delete all objects in bucket_name under key_prefix."""
    response = await minio_client.list_objects_v2(Bucket=bucket_name, Prefix=key_prefix)

    if "Contents" in response:
        for obj in response["Contents"]:
            if "Key" in obj:
                await minio_client.delete_object(Bucket=bucket_name, Key=obj["Key"])


def test_can_run_s3_test_step_for_new_destination(client: HttpClient, bucket_name, minio_client):
    destination_data = {
        "type": "S3",
        "config": {
            "bucket_name": bucket_name,
            "region": "us-east-1",
            "prefix": "posthog-events/",
            "aws_access_key_id": "object_storage_root_user",
            "aws_secret_access_key": "object_storage_root_password",
            "endpoint_url": settings.OBJECT_STORAGE_ENDPOINT,
        },
    }

    batch_export_data = {
        "name": "my-production-s3-bucket-destination",
        "destination": destination_data,
        "interval": "hour",
    }

    organization = create_organization("Test Org")
    team = create_team(organization)
    user = create_user("test@user.com", "Test User", organization)
    client.force_login(user)

    response = client.post(
        f"/api/projects/{team.pk}/batch_exports/run_test_step_new",
        {**{"step": 0}, **batch_export_data},
        content_type="application/json",
    )

    assert response.status_code == status.HTTP_200_OK, response.json()

    destination_test = response.json()

    assert destination_test["result"]["status"] == "Passed", destination_test
    assert destination_test["result"]["message"] is None


def test_can_run_s3_test_step_for_destination(client: HttpClient, bucket_name, minio_client, temporal):
    destination_data = {
        "type": "S3",
        "config": {
            "bucket_name": bucket_name,
            "region": "us-east-1",
            "prefix": "posthog-events/",
            "aws_access_key_id": "object_storage_root_user",
            "aws_secret_access_key": "object_storage_root_password",
            "endpoint_url": settings.OBJECT_STORAGE_ENDPOINT,
        },
    }

    batch_export_data = {
        "name": "my-production-s3-bucket-destination",
        "destination": destination_data,
        "interval": "hour",
    }

    organization = create_organization("Test Org")
    team = create_team(organization)
    user = create_user("test@user.com", "Test User", organization)
    client.force_login(user)

    with start_test_worker(temporal):
        batch_export = create_batch_export_ok(
            client,
            team.pk,
            batch_export_data,
        )

        response = client.post(
            f"/api/projects/{team.pk}/batch_exports/{batch_export['id']}/run_test_step",
            {**{"step": 0}, **batch_export_data},
            content_type="application/json",
        )

    assert response.status_code == status.HTTP_200_OK, response.json()

    destination_test = response.json()

    assert destination_test["result"]["status"] == "Passed", destination_test
    assert destination_test["result"]["message"] is None
