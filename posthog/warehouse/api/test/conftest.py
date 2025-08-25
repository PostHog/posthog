import logging

import pytest

import psycopg
import pytest_asyncio
from asgiref.sync import async_to_sync
from psycopg import sql
from temporalio.client import Client as TemporalClient
from temporalio.service import RPCError

from posthog.temporal.common.client import sync_connect
from posthog.warehouse.models import ExternalDataSchema


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


@async_to_sync
async def delete_temporal_schedule(temporal: TemporalClient, schedule_id: str):
    """Delete a Temporal Schedule with the given id."""
    handle = temporal.get_schedule_handle(schedule_id)
    await handle.delete()


def cleanup_temporal_schedules(client):
    """Clean up any Temporal Schedules created during the test."""
    for schedule in ExternalDataSchema.objects.all():
        try:
            delete_temporal_schedule(client, str(schedule.id))
        except RPCError:
            # Assume this is fine as we are tearing down, but don't fail silently.
            logging.warning("Schedule %s has already been deleted, ignoring.", schedule.id)
            continue


@pytest.fixture
def temporal():
    """Return a TemporalClient instance."""
    client = sync_connect()
    yield client
    cleanup_temporal_schedules(client)
