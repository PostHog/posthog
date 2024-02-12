import psycopg
import pytest
import pytest_asyncio
from psycopg import sql


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
