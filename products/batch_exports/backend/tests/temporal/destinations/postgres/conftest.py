import uuid
from collections.abc import AsyncIterator

import pytest

from django.conf import settings

import psycopg
import pytest_asyncio
from psycopg import sql

from posthog.models import Integration

from products.batch_exports.backend.tests.temporal.destinations.postgres.utils import make_integration


@pytest.fixture
def postgres_config():
    return {
        "user": settings.PG_USER,
        "password": settings.PG_PASSWORD,
        "database": "exports_test_database",
        "schema": "exports_test_schema",
        "host": settings.PG_HOST,
        "port": int(settings.PG_PORT),
    }


@pytest_asyncio.fixture
async def postgres_connection(postgres_config, setup_postgres_test_db):
    connection = await psycopg.AsyncConnection.connect(
        user=postgres_config["user"],
        password=postgres_config["password"],
        dbname=postgres_config["database"],
        host=postgres_config["host"],
        port=postgres_config["port"],
        autocommit=True,
    )

    yield connection

    await connection.close()


@pytest_asyncio.fixture
async def insert_only_postgres_config(
    request: pytest.FixtureRequest, postgres_connection: psycopg.AsyncConnection, postgres_config: dict[str, str | int]
) -> AsyncIterator[dict[str, str | int]]:
    if not request.param:
        yield postgres_config
        return

    role_name = f"batch_export_insert_only_{uuid.uuid4().hex}"
    role = sql.Identifier(role_name)
    password = uuid.uuid4().hex
    async with postgres_connection.cursor() as cursor:
        await cursor.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(role, sql.Literal(password)))
        try:
            await cursor.execute(
                sql.SQL("GRANT USAGE, CREATE ON SCHEMA {} TO {}").format(
                    sql.Identifier(str(postgres_config["schema"])), role
                )
            )
            yield {**postgres_config, "user": role_name, "password": password}
        finally:
            await cursor.execute(sql.SQL("DROP OWNED BY {}").format(role))
            await cursor.execute(sql.SQL("DROP ROLE {}").format(role))


@pytest.fixture
def test_properties(request, session_id):
    """Include some problematic properties."""
    try:
        return request.param
    except AttributeError:
        return {
            "$browser": "Chrome",
            "$os": "Mac OS X",
            "$session_id": session_id,
            "unicode_null": "\u0000",
            "emoji": "🤣",
            "newline": "\n",
            # URL with curly braces, which needs to be escaped when converted to a PostgreSQL array.
            "$current_url": "https://www.posthog.com#link={foo}",
        }


@pytest.fixture
def table_name(ateam, interval):
    return f"test_table_{ateam.pk}_{interval}"


@pytest_asyncio.fixture
async def postgres_batch_export(ateam, table_name, postgres_config, interval, exclude_events, temporal_client):
    from posthog.temporal.tests.utils.models import acreate_batch_export, adelete_batch_export

    destination_data = {
        "type": "Postgres",
        "config": {**postgres_config, "table_name": table_name, "exclude_events": exclude_events},
    }
    batch_export_data = {
        "name": "my-production-postgres-export",
        "destination": destination_data,
        "interval": interval,
    }

    batch_export = await acreate_batch_export(
        team_id=ateam.pk,
        name=batch_export_data["name"],
        destination_data=batch_export_data["destination"],
        interval=batch_export_data["interval"],
    )

    yield batch_export

    await adelete_batch_export(batch_export, temporal_client)


@pytest_asyncio.fixture
async def integration(request, ateam, postgres_config) -> Integration | None:
    try:
        use_integration = request.param
    except Exception:
        return None

    if not use_integration:
        return None

    integration = await make_integration(ateam.pk, postgres_config)
    return integration
