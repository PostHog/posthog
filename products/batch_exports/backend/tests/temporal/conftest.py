import uuid
import random
import asyncio
import datetime as dt

import pytest

from django.conf import settings

import psycopg
import temporalio.worker
from asgiref.sync import sync_to_async
from infi.clickhouse_orm import Database
from psycopg import sql
from temporalio.testing import ActivityEnvironment

from posthog.conftest import create_clickhouse_tables
from posthog.models import Organization, Team
from posthog.models.utils import uuid7
from posthog.temporal.common.clickhouse import ClickHouseClient
from posthog.temporal.common.client import connect
from posthog.temporal.common.logger import configure_logger
from posthog.temporal.tests.utils.events import generate_test_events_in_clickhouse

from products.batch_exports.backend.temporal.metrics import BatchExportsMetricsInterceptor
from products.batch_exports.backend.tests.temporal.utils.persons import (
    generate_test_person_distinct_id2_in_clickhouse,
    generate_test_persons_in_clickhouse,
)


@pytest.fixture(scope="package", autouse=True)
def clickhouse_create_db_and_tables():
    database = Database(
        settings.CLICKHOUSE_DATABASE,
        db_url=settings.CLICKHOUSE_HTTP_URL,
        username=settings.CLICKHOUSE_USER,
        password=settings.CLICKHOUSE_PASSWORD,
        cluster=settings.CLICKHOUSE_CLUSTER,
        verify_ssl_cert=settings.CLICKHOUSE_VERIFY,
        randomize_replica_paths=True,
    )

    database.create_database()  # Create database if it doesn't exist
    create_clickhouse_tables()  # Create all expected tables

    yield


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


@pytest.fixture
async def aorganization():
    name = f"BatchExportsTestOrg-{random.randint(1, 99999)}"
    org = await sync_to_async(Organization.objects.create)(name=name, is_ai_data_processing_approved=True)

    yield org

    await sync_to_async(org.delete)()


@pytest.fixture
async def ateam(aorganization):
    name = f"BatchExportsTestTeam-{random.randint(1, 99999)}"
    team = await sync_to_async(Team.objects.create)(organization=aorganization, name=name)

    yield team

    await sync_to_async(team.delete)()


@pytest.fixture
def activity_environment():
    """Return a testing temporal ActivityEnvironment."""
    return ActivityEnvironment()


@pytest.fixture(scope="module")
async def clickhouse_client(event_loop):
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


@pytest.fixture
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


@pytest.fixture()
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


@pytest.fixture()
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


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(autouse=True, scope="module")
async def configure_logger_auto() -> None:
    """Configure logger when running in a Temporal activity environment."""
    configure_logger(cache_logger_on_first_use=False)


@pytest.fixture
def interval(request) -> str:
    """A parametrizable fixture to configure a batch export interval.

    By decorating a test function with @pytest.mark.parametrize("interval", ..., indirect=True)
    it's possible to set the interval that will be used to create a BatchExport.
    Possible values are "hour", "day", or "every {value} {unit}".
    As interval must be defined for every BatchExport, so we default to "hour" to
    support tests that do not parametrize this.
    """
    try:
        return request.param
    except AttributeError:
        return "hour"


@pytest.fixture
def exclude_events(request) -> list[str] | None:
    """A parametrizable fixture to configure event names to exclude from a BatchExport.

    By decorating a test function with @pytest.mark.parametrize("exclude_events", ..., indirect=True)
    it's possible to set the exclude_events that will be used to create a BatchExport.
    Any list of event names can be used, or None (the default).
    """
    try:
        return request.param
    except AttributeError:
        return None


@pytest.fixture
def batch_export_schema(request) -> dict | None:
    """A parametrizable fixture to configure a batch export schema.

    By decorating a test function with @pytest.mark.parametrize("batch_export_schema", ..., indirect=True)
    it's possible to set the batch_export_schema that will be used to create a BatchExport.
    """
    try:
        return request.param
    except AttributeError:
        return None


@pytest.fixture
async def setup_postgres_test_db(postgres_config):
    """Fixture to manage a database for Redshift and Postgres export testing.

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


@pytest.fixture
async def temporal_worker(temporal_client, workflows, activities):
    worker = temporalio.worker.Worker(
        temporal_client,
        task_queue=settings.BATCH_EXPORTS_TASK_QUEUE,
        workflows=workflows,
        activities=activities,
        interceptors=[BatchExportsMetricsInterceptor()],
        workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
    )

    worker_run = asyncio.create_task(worker.run())

    yield worker

    worker_run.cancel()
    await asyncio.wait([worker_run])


@pytest.fixture
def data_interval_start(request, data_interval_end, interval):
    """Set a test interval start based on interval end and interval."""
    try:
        return request.param
    except AttributeError:
        pass

    if interval == "hour":
        interval_time_delta = dt.timedelta(hours=1)
    elif interval == "day":
        interval_time_delta = dt.timedelta(days=1)
    elif interval == "week":
        interval_time_delta = dt.timedelta(weeks=1)
    elif interval.startswith("every"):
        _, value, unit = interval.split(" ")
        kwargs = {unit: int(value)}
        interval_time_delta = dt.timedelta(**kwargs)
    else:
        raise ValueError(f"Invalid interval: '{interval}'")

    return data_interval_end - interval_time_delta


@pytest.fixture
def data_interval_end(request, interval):
    """Set a test data interval end.

    This defaults to the current day at 00:00 UTC. This is done because event data is only available in events_recent
    for the last 7 days, so if we try to insert data further in the past, it may be deleted and lead to flaky tests.
    """
    try:
        return request.param
    except AttributeError:
        pass
    return dt.datetime.now(tz=dt.UTC).replace(hour=0, minute=0, second=0, microsecond=0)


@pytest.fixture
def session_id(request) -> str:
    try:
        return request.param
    except AttributeError:
        pass
    return str(uuid7())


@pytest.fixture
def test_properties(request, session_id):
    """Set test data properties."""
    try:
        return {**{"$session_id": session_id}, **request.param}
    except AttributeError:
        pass
    return {"$browser": "Chrome", "$os": "Mac OS X", "prop": "value", "$session_id": session_id}


@pytest.fixture
def insert_sessions(request):
    """Sets whether to insert new sessions or not."""
    try:
        return request.param
    except AttributeError:
        pass
    return True


@pytest.fixture
def test_person_properties(request):
    """Set test person data properties."""
    try:
        return request.param
    except AttributeError:
        pass
    return {"utm_medium": "referral", "$initial_os": "Linux"}


@pytest.fixture
async def generate_test_data(
    ateam,
    clickhouse_client,
    exclude_events,
    data_interval_start,
    data_interval_end,
    test_properties,
    test_person_properties,
    insert_sessions,
):
    """Generate test data in ClickHouse."""
    if data_interval_start and data_interval_start > (dt.datetime.now(tz=dt.UTC) - dt.timedelta(days=6)):
        table = "events_recent"
    else:
        table = "sharded_events"

    events_to_export_created, _, _ = await generate_test_events_in_clickhouse(
        client=clickhouse_client,
        team_id=ateam.pk,
        start_time=data_interval_start,
        end_time=data_interval_end,
        count=1000,
        count_outside_range=10,
        count_other_team=10,
        duplicate=True,
        properties=test_properties,
        person_properties={"utm_medium": "referral", "$initial_os": "Linux"},
        table=table,
        insert_sessions="$session_id" in test_properties and insert_sessions,
    )

    more_events_to_export_created, _, _ = await generate_test_events_in_clickhouse(
        client=clickhouse_client,
        team_id=ateam.pk,
        start_time=data_interval_start,
        end_time=data_interval_end,
        count=5,
        count_outside_range=0,
        count_other_team=0,
        properties=None,
        person_properties=None,
        event_name="test-no-prop-{i}",
        table=table,
    )
    events_to_export_created.extend(more_events_to_export_created)

    if exclude_events:
        for event_name in exclude_events:
            await generate_test_events_in_clickhouse(
                client=clickhouse_client,
                team_id=ateam.pk,
                start_time=data_interval_start,
                end_time=data_interval_end,
                count=5,
                count_outside_range=0,
                count_other_team=0,
                event_name=event_name,
                table=table,
            )

    persons, _ = await generate_test_persons_in_clickhouse(
        client=clickhouse_client,
        team_id=ateam.pk,
        start_time=data_interval_start,
        end_time=data_interval_end,
        count=10,
        count_other_team=1,
        properties=test_person_properties,
    )

    persons_to_export_created = []
    for person in persons:
        person_distinct_id, _ = await generate_test_person_distinct_id2_in_clickhouse(
            client=clickhouse_client,
            team_id=ateam.pk,
            person_id=uuid.UUID(person["id"]),
            distinct_id=f"distinct-id-{uuid.UUID(person['id'])}",
            timestamp=dt.datetime.fromisoformat(person["_timestamp"]),
        )
        person_to_export = {
            "team_id": person["team_id"],
            "person_id": person["id"],
            "distinct_id": person_distinct_id["distinct_id"],
            "version": person_distinct_id["version"],
            "_timestamp": dt.datetime.fromisoformat(person["_timestamp"]),
        }
        persons_to_export_created.append(person_to_export)

    return (events_to_export_created, persons_to_export_created)


@pytest.fixture
async def generate_test_persons_data(ateam, clickhouse_client, data_interval_start, data_interval_end):
    """Generate test persons data in ClickHouse."""
    persons, _ = await generate_test_persons_in_clickhouse(
        client=clickhouse_client,
        team_id=ateam.pk,
        start_time=data_interval_start,
        end_time=data_interval_end,
        count=10,
        count_other_team=1,
        properties={"utm_medium": "referral", "$initial_os": "Linux"},
    )

    persons_to_export_created = []
    for person in persons:
        person_distinct_id, _ = await generate_test_person_distinct_id2_in_clickhouse(
            client=clickhouse_client,
            team_id=ateam.pk,
            person_id=uuid.UUID(person["id"]),
            distinct_id=f"distinct-id-{uuid.UUID(person['id'])}",
            timestamp=dt.datetime.fromisoformat(person["_timestamp"]),
        )
        person_to_export = {
            "team_id": person["team_id"],
            "person_id": person["id"],
            "distinct_id": person_distinct_id["distinct_id"],
            "version": person_distinct_id["version"],
            "_timestamp": dt.datetime.fromisoformat(person["_timestamp"]),
        }
        persons_to_export_created.append(person_to_export)

    return persons_to_export_created
