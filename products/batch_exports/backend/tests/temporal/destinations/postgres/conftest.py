import pytest

from django.conf import settings

import psycopg

from products.batch_exports.backend.temporal.destinations.postgres_batch_export import PostgreSQLHeartbeatDetails


@pytest.fixture
def activity_environment(activity_environment):
    activity_environment.heartbeat_class = PostgreSQLHeartbeatDetails
    return activity_environment


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


@pytest.fixture
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
        }


@pytest.fixture
def table_name(ateam, interval):
    return f"test_table_{ateam.pk}_{interval}"


@pytest.fixture
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
