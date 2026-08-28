import uuid
import functools

import pytest

from django.conf import settings

import aioboto3
import pytest_asyncio

# The activity-log post_save signal lazily imports posthog.api.advanced_activity_logs
# (-> posthog.tasks.usage_report) the first time an ActivityLog row is created. In these
# temporal tests the worker logger has already reconfigured structlog to a WrapperLogger,
# under which usage_report's module-level logger.setLevel() raises AttributeError and crashes
# fixture setup. Importing the chain here — while structlog is still the default config —
# runs that module-level code safely and caches it, so the signal's lazy import is a no-op.
import posthog.api.advanced_activity_logs  # noqa: F401, E402 — warm import; see comment above
from posthog.sync import database_sync_to_async

from products.data_modeling.backend.facade.models import DAG, DataModelingJob, DataWarehouseSavedQuery, Node, NodeType

TEST_ROOT_BUCKET = "test-data-modeling"
SESSION = aioboto3.Session()
create_test_client = functools.partial(SESSION.client, endpoint_url=settings.OBJECT_STORAGE_ENDPOINT)


@pytest.fixture
def bucket_name(request) -> str:
    try:
        return request.param
    except AttributeError:
        return f"{TEST_ROOT_BUCKET}-{uuid.uuid4()}"


@pytest_asyncio.fixture
async def minio_client(bucket_name):
    async with create_test_client(
        "s3",
        aws_access_key_id=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
        aws_secret_access_key=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
    ) as client:
        try:
            await client.head_bucket(Bucket=bucket_name)
        except Exception:
            await client.create_bucket(Bucket=bucket_name)

        yield client


@pytest_asyncio.fixture
async def asaved_query(ateam, auser):
    query = await database_sync_to_async(DataWarehouseSavedQuery.objects.create)(
        team=ateam,
        name="test_model",
        query={"query": "SELECT 1", "kind": "HogQLQuery"},
        created_by=auser,
    )
    yield query
    await database_sync_to_async(query.delete)()


@pytest_asyncio.fixture
async def adag(ateam):
    dag = await database_sync_to_async(DAG.objects.create)(team=ateam, name="test-dag")
    yield dag
    await database_sync_to_async(dag.delete)()


@pytest_asyncio.fixture
async def anode(ateam, asaved_query, adag):
    node = await database_sync_to_async(Node.objects.create)(
        team=ateam,
        saved_query=asaved_query,
        dag=adag,
        name="test_model",
        type=NodeType.MAT_VIEW,
    )
    yield node
    await database_sync_to_async(node.delete)()


@pytest_asyncio.fixture
async def ajob(ateam, asaved_query):
    job = await database_sync_to_async(DataModelingJob.objects.create)(
        team=ateam,
        saved_query=asaved_query,
        status=DataModelingJob.Status.RUNNING,
        workflow_id="test-workflow",
    )
    yield job
    await database_sync_to_async(job.delete)()
