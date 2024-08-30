import asyncio
import functools
import unittest.mock
import uuid

import aioboto3
import pytest
import pytest_asyncio
from django.conf import settings
from django.test import override_settings
from dlt.common.configuration.specs.aws_credentials import AwsCredentials

from posthog.temporal.data_modeling.run_workflow import (
    ModelNode,
    RunModelActivityInputs,
    materialize_model,
    run_model_activity,
)
from posthog.warehouse.models.datawarehouse_saved_query import DataWarehouseSavedQuery

pytestmark = [pytest.mark.asyncio, pytest.mark.django_db]


async def test_run_model_activity_activity_materialize_mocked(activity_environment, ateam):
    nodes_map = {
        "my_events_model": ModelNode(label="my_events_model", children={"my_joined_model"}, parents=set()),
        "my_persons_model": ModelNode(label="my_persons_model", children={"my_joined_model"}, parents=set()),
        "my_joined_model": ModelNode(
            label="my_joined_model", children=set(), parents={"my_events_model", "my_persons_model"}
        ),
    }
    run_model_activity_inputs = RunModelActivityInputs(team_id=ateam.pk, nodes_map=nodes_map)

    magic_mock = unittest.mock.AsyncMock()
    with unittest.mock.patch("posthog.temporal.data_modeling.run_workflow.materialize_model", new=magic_mock):
        async with asyncio.timeout(10):
            results = await activity_environment.run(run_model_activity, run_model_activity_inputs)

        calls = [unittest.mock.call(k, ateam) for k in nodes_map.keys()]
        magic_mock.assert_has_calls(calls)

    assert results.completed == {"my_events_model", "my_persons_model", "my_joined_model"}


TEST_ROOT_BUCKET = "test-data-modeling"
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
        aws_access_key_id=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
        aws_secret_access_key=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
    ) as minio_client:
        try:
            await minio_client.head_bucket(Bucket=bucket_name)
        except:
            await minio_client.create_bucket(Bucket=bucket_name)

        yield minio_client


def mock_to_session_credentials(class_self):
    return {
        "aws_access_key_id": settings.OBJECT_STORAGE_ACCESS_KEY_ID,
        "aws_secret_access_key": settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
        "endpoint_url": settings.OBJECT_STORAGE_ENDPOINT,
        "aws_session_token": None,
        "AWS_ALLOW_HTTP": "true",
        "AWS_S3_ALLOW_UNSAFE_RENAME": "true",
    }


def mock_to_object_store_rs_credentials(class_self):
    return {
        "aws_access_key_id": settings.OBJECT_STORAGE_ACCESS_KEY_ID,
        "aws_secret_access_key": settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
        "endpoint_url": settings.OBJECT_STORAGE_ENDPOINT,
        "region": "us-east-1",
        "AWS_ALLOW_HTTP": "true",
        "AWS_S3_ALLOW_UNSAFE_RENAME": "true",
    }


async def test_materialize_model(ateam, bucket_name):
    query = """\
    select event as event, distinct_id as distinct_id, timestamp as timestamp
    from events where event = '$pageview'
    """
    saved_query = await DataWarehouseSavedQuery.objects.acreate(
        team=ateam,
        name="my_model",
        query={"query": query},
    )

    with (
        override_settings(
            BUCKET_URL=f"s3://{bucket_name}",
            AIRBYTE_BUCKET_KEY=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
            AIRBYTE_BUCKET_SECRET=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
            AIRBYTE_BUCKET_REGION="us-east-1",
            AIRBYTE_BUCKET_DOMAIN="objectstorage:19000",
        ),
        unittest.mock.patch.object(AwsCredentials, "to_session_credentials", mock_to_session_credentials),
        unittest.mock.patch.object(
            AwsCredentials, "to_object_store_rs_credentials", mock_to_object_store_rs_credentials
        ),
    ):
        await materialize_model(saved_query.id.hex, ateam)
