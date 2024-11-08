import asyncio
import datetime as dt
import uuid

import psycopg
import pytest
import pytest_asyncio
from psycopg import sql
from temporalio.testing import ActivityEnvironment

from posthog.temporal.common.utils import BatchExportRangeHeartbeatDetails, HeartbeatType
from posthog.temporal.tests.utils.events import generate_test_events_in_clickhouse
from posthog.temporal.tests.utils.persons import (
    generate_test_person_distinct_id2_in_clickhouse,
    generate_test_persons_in_clickhouse,
)


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


@pytest_asyncio.fixture(autouse=True)
async def truncate_events(clickhouse_client):
    """Fixture to automatically truncate sharded_events after a test.

    This is useful if during the test setup we insert a lot of events we wish to clean-up.
    """
    yield
    await clickhouse_client.execute_query("TRUNCATE TABLE IF EXISTS `sharded_events`")


@pytest_asyncio.fixture(autouse=True)
async def truncate_persons(clickhouse_client):
    """Fixture to automatically truncate person and person_distinct_id2 after a test.

    This is useful if during the test setup we insert a lot of persons we wish to clean-up.
    """
    yield
    await clickhouse_client.execute_query("TRUNCATE TABLE IF EXISTS `person`")
    await clickhouse_client.execute_query("TRUNCATE TABLE IF EXISTS `person_distinct_id2`")


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


@pytest_asyncio.fixture
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


@pytest_asyncio.fixture(scope="module", autouse=True)
async def create_clickhouse_tables_and_views(clickhouse_client, django_db_setup):
    from posthog.batch_exports.sql import (
        CREATE_EVENTS_BATCH_EXPORT_VIEW,
        CREATE_EVENTS_BATCH_EXPORT_VIEW_BACKFILL,
        CREATE_EVENTS_BATCH_EXPORT_VIEW_UNBOUNDED,
        CREATE_PERSONS_BATCH_EXPORT_VIEW,
        CREATE_PERSONS_BATCH_EXPORT_VIEW_BACKFILL,
    )
    from posthog.clickhouse.schema import CREATE_KAFKA_TABLE_QUERIES, build_query

    create_view_queries = (
        CREATE_EVENTS_BATCH_EXPORT_VIEW,
        CREATE_EVENTS_BATCH_EXPORT_VIEW_BACKFILL,
        CREATE_EVENTS_BATCH_EXPORT_VIEW_UNBOUNDED,
        CREATE_PERSONS_BATCH_EXPORT_VIEW,
        CREATE_PERSONS_BATCH_EXPORT_VIEW_BACKFILL,
    )

    clickhouse_tasks = set()
    for query in create_view_queries + tuple(map(build_query, CREATE_KAFKA_TABLE_QUERIES)):
        task = asyncio.create_task(clickhouse_client.execute_query(query))
        clickhouse_tasks.add(task)
        task.add_done_callback(clickhouse_tasks.discard)

    done, pending = await asyncio.wait(clickhouse_tasks)

    if len(pending) > 0:
        raise ValueError("Not all required tables and views were created in time")

    for task in done:
        if exc := task.exception():
            raise exc

    return


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
def data_interval_end(interval):
    """Set a test data interval end."""
    return dt.datetime(2023, 4, 25, 15, 0, 0, tzinfo=dt.UTC)


@pytest_asyncio.fixture
async def generate_test_data(ateam, clickhouse_client, exclude_events, data_interval_start, data_interval_end):
    """Generate test data in ClickHouse."""
    events_to_export_created, _, _ = await generate_test_events_in_clickhouse(
        client=clickhouse_client,
        team_id=ateam.pk,
        start_time=data_interval_start,
        end_time=data_interval_end,
        count=1000,
        count_outside_range=10,
        count_other_team=10,
        duplicate=True,
        properties={"$browser": "Chrome", "$os": "Mac OS X"},
        person_properties={"utm_medium": "referral", "$initial_os": "Linux"},
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
            )

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

    return (events_to_export_created, persons_to_export_created)


class HeartbeatActivityEnvironment(ActivityEnvironment):
    def __init__(self, *args, heartbeat_cls: type[HeartbeatType] = BatchExportRangeHeartbeatDetails, **kwargs):
        super().__init__(*args, **kwargs)
        self.track_heartbeat_details = []
        self.heartbeat_cls = heartbeat_cls
        self.on_heartbeat = self.call_on_heartbeat

    def call_on_heartbeat(self, *details):
        """Record heartbeat details received."""
        details = self.heartbeat_cls.from_activity_details(details)
        self.track_heartbeat_details.append(details)


@pytest.fixture
def activity_environment():
    """Return a testing temporal ActivityEnvironment."""
    return HeartbeatActivityEnvironment()
