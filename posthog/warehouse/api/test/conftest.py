import psycopg
import pytest_asyncio
from psycopg import sql


@pytest_asyncio.fixture
async def setup_postgres_test_db(postgres_config):
    """Fixture to manage a database for Postgres export testing.

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
