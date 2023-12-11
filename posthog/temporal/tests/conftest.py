import asyncio
import random

import pytest
import pytest_asyncio
import temporalio.worker
from asgiref.sync import sync_to_async
from django.conf import settings
from temporalio.testing import ActivityEnvironment

from posthog.models import Organization, Team
from posthog.temporal.batch_exports.clickhouse import ClickHouseClient
from posthog.temporal.common.client import connect


@pytest.fixture
def organization():
    """A test organization."""
    name = f"BatchExportsTestOrg-{random.randint(1, 99999)}"
    org = Organization.objects.create(name=name)
    org.save()

    yield org

    org.delete()


@pytest.fixture
def team(organization):
    """A test team."""
    name = f"BatchExportsTestTeam-{random.randint(1, 99999)}"
    team = Team.objects.create(organization=organization, name=name)
    team.save()

    yield team

    team.delete()


@pytest_asyncio.fixture
async def aorganization():
    name = f"BatchExportsTestOrg-{random.randint(1, 99999)}"
    org = await sync_to_async(Organization.objects.create)(name=name)

    yield org

    await sync_to_async(org.delete)()


@pytest_asyncio.fixture
async def ateam(aorganization):
    name = f"BatchExportsTestTeam-{random.randint(1, 99999)}"
    team = await sync_to_async(Team.objects.create)(organization=aorganization, name=name)

    yield team

    await sync_to_async(team.delete)()


@pytest.fixture
def activity_environment():
    """Return a testing temporal ActivityEnvironment."""
    return ActivityEnvironment()


@pytest.fixture
def clickhouse_client():
    """Provide a ClickHouseClient to use in tests."""
    client = ClickHouseClient(
        url=settings.CLICKHOUSE_HTTP_URL,
        user=settings.CLICKHOUSE_USER,
        password=settings.CLICKHOUSE_PASSWORD,
        database=settings.CLICKHOUSE_DATABASE,
    )

    yield client


@pytest_asyncio.fixture
async def temporal_client():
    """Provide a temporalio.client.Client to use in tests."""
    client = await connect(
        settings.TEMPORAL_HOST,
        settings.TEMPORAL_PORT,
        settings.TEMPORAL_NAMESPACE,
        settings.TEMPORAL_CLIENT_ROOT_CA,
        settings.TEMPORAL_CLIENT_CERT,
        settings.TEMPORAL_CLIENT_KEY,
    )

    yield client


@pytest_asyncio.fixture()
async def workflows(request):
    """Return Temporal workflows to initialize a test worker.

    By default (no parametrization), we return all available workflows. Optionally,
    with @pytest.mark.parametrize it is possible to customize which workflows the worker starts with.
    """
    try:
        return request.param
    except AttributeError:
        from posthog.temporal.batch_exports import WORKFLOWS

        return WORKFLOWS


@pytest_asyncio.fixture()
async def activities(request):
    """Return Temporal activities to initialize a test worker.

    By default (no parametrization), we return all available activities. Optionally,
    with @pytest.mark.parametrize it is possible to customize which activities the worker starts with.
    """
    try:
        return request.param
    except AttributeError:
        from posthog.temporal.batch_exports import ACTIVITIES

        return ACTIVITIES


@pytest_asyncio.fixture
async def temporal_worker(temporal_client, workflows, activities):
    worker = temporalio.worker.Worker(
        temporal_client,
        task_queue=settings.TEMPORAL_TASK_QUEUE,
        workflows=workflows,
        activities=activities,
        workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
    )

    worker_run = asyncio.create_task(worker.run())

    yield worker

    worker_run.cancel()
    await asyncio.wait([worker_run])
