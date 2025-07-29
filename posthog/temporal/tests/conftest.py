import asyncio
import random

import psycopg
import pytest
import pytest_asyncio
import temporalio.worker
from asgiref.sync import sync_to_async
from django.conf import settings
from psycopg import sql
from temporalio.testing import ActivityEnvironment

from posthog.otel_instrumentation import initialize_otel
from posthog.models import Organization, Team
from posthog.temporal.common.clickhouse import ClickHouseClient
from posthog.temporal.common.client import connect


@pytest.fixture
def organization():
    """A test organization."""
    name = f"BatchExportsTestOrg-{random.randint(1, 99999)}"
    org = Organization.objects.create(name=name, is_ai_data_processing_approved=True)
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
    org = await sync_to_async(Organization.objects.create)(name=name, is_ai_data_processing_approved=True)

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


@pytest_asyncio.fixture(scope="module")
async def clickhouse_client():
    """Provide a ClickHouseClient to use in tests."""
    async with ClickHouseClient(
        url=settings.CLICKHOUSE_HTTP_URL,
        user=settings.CLICKHOUSE_USER,
        password=settings.CLICKHOUSE_PASSWORD,
        database=settings.CLICKHOUSE_DATABASE,
        output_format_arrow_string_as_string="true",
        # This parameter is disabled (0) in production.
        # Durting testing, it's useful to enable it to wait for mutations.
        # Otherwise, tests that rely on running a mutation may become flaky.
        mutations_sync=2,
    ) as client:
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
        from products.batch_exports.backend.temporal import WORKFLOWS

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
        from products.batch_exports.backend.temporal import ACTIVITIES

        return ACTIVITIES


@pytest_asyncio.fixture
async def temporal_worker(temporal_client, workflows, activities):
    initialize_otel()

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


@pytest.fixture(scope="session")
def event_loop():
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture
async def setup_postgres_test_db(postgres_config):
    """Fixture to manage a database for Redshift export testing.

    Managing a test database involves the following steps:
    1. Creating a test database.
    2. Initializing a connection to that database.
    3. Creating a test schema.
    4. Yielding the connection to be used in tests.
    5. After tests, drop the test schema and any tables in it.
    6. Drop the test database.
    """
    connection = await psycopg.AsyncConnection.connect(
        user=postgres_config["user"],
        password=postgres_config["password"],
        host=postgres_config["host"],
        port=postgres_config["port"],
    )
    await connection.set_autocommit(True)

    async with connection.cursor() as cursor:
        await cursor.execute(
            sql.SQL("SELECT 1 FROM pg_database WHERE datname = %s"),
            (postgres_config["database"],),
        )

        if await cursor.fetchone() is None:
            await cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(postgres_config["database"])))

    await connection.close()

    # We need a new connection to connect to the database we just created.
    connection = await psycopg.AsyncConnection.connect(
        user=postgres_config["user"],
        password=postgres_config["password"],
        host=postgres_config["host"],
        port=postgres_config["port"],
        dbname=postgres_config["database"],
    )
    await connection.set_autocommit(True)

    async with connection.cursor() as cursor:
        await cursor.execute(
            sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(postgres_config["schema"]))
        )

    yield

    async with connection.cursor() as cursor:
        await cursor.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(postgres_config["schema"])))

    await connection.close()

    # We need a new connection to drop the database, as we cannot drop the current database.
    connection = await psycopg.AsyncConnection.connect(
        user=postgres_config["user"],
        password=postgres_config["password"],
        host=postgres_config["host"],
        port=postgres_config["port"],
    )
    await connection.set_autocommit(True)

    async with connection.cursor() as cursor:
        await cursor.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(postgres_config["database"])))

    await connection.close()
