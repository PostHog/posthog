import os
import tempfile
from collections.abc import AsyncGenerator
from uuid import uuid4

import pytest

import snowflake.connector

from posthog.batch_exports.models import BatchExport
from posthog.temporal.tests.utils.models import acreate_batch_export, adelete_batch_export

from products.batch_exports.backend.temporal.destinations.snowflake_batch_export import load_private_key


@pytest.fixture
def database():
    """Generate a unique database name for tests."""
    return f"test_batch_exports_{uuid4()}"


@pytest.fixture
def schema():
    """Generate a unique schema name for tests."""
    return f"test_batch_exports_{uuid4()}"


@pytest.fixture
def table_name(ateam, interval):
    return f"test_workflow_table_{ateam.pk}_{interval}"


@pytest.fixture
def snowflake_config(database, schema) -> dict[str, str]:
    """Return a Snowflake configuration dictionary to use in tests.

    We set default configuration values to support tests against the Snowflake API
    and tests that mock it.
    """
    warehouse = os.getenv("SNOWFLAKE_WAREHOUSE", "warehouse")
    account = os.getenv("SNOWFLAKE_ACCOUNT", "account")
    role = os.getenv("SNOWFLAKE_ROLE", None)
    username = os.getenv("SNOWFLAKE_USERNAME", "username")
    password = os.getenv("SNOWFLAKE_PASSWORD", "password")
    private_key = os.getenv("SNOWFLAKE_PRIVATE_KEY")
    private_key_passphrase = os.getenv("SNOWFLAKE_PRIVATE_KEY_PASSPHRASE")

    config = {
        "user": username,
        "warehouse": warehouse,
        "account": account,
        "database": database,
        "schema": schema,
        "role": role,
    }
    if private_key:
        config["private_key"] = private_key
        config["private_key_passphrase"] = private_key_passphrase
        config["authentication_type"] = "keypair"
    elif password:
        config["password"] = password
        config["authentication_type"] = "password"
    else:
        raise ValueError("Either password or private key must be set")
    return config


@pytest.fixture
async def snowflake_batch_export(
    ateam, table_name, snowflake_config, interval, exclude_events, temporal_client
) -> AsyncGenerator[BatchExport, None]:
    """Manage BatchExport model (and associated Temporal Schedule) for tests"""
    destination_data = {
        "type": "Snowflake",
        "config": {**snowflake_config, "table_name": table_name, "exclude_events": exclude_events},
    }
    batch_export_data = {
        "name": "my-production-snowflake-export",
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


@pytest.fixture
def snowflake_cursor(snowflake_config: dict[str, str]):
    """Manage a snowflake cursor that cleans up after we are done."""
    password = None
    private_key = None
    if snowflake_config["authentication_type"] == "keypair":
        if snowflake_config.get("private_key") is None:
            raise ValueError("Private key is required for keypair authentication")

        private_key = load_private_key(snowflake_config["private_key"], snowflake_config["private_key_passphrase"])
    else:
        password = snowflake_config["password"]

    with snowflake.connector.connect(
        user=snowflake_config["user"],
        password=password,
        account=snowflake_config["account"],
        role=f'"{snowflake_config["role"]}"' if snowflake_config["role"] is not None else None,
        warehouse=snowflake_config["warehouse"],
        private_key=private_key,
    ) as connection:
        connection.telemetry_enabled = False
        cursor = connection.cursor()
        cursor.execute(f'CREATE DATABASE "{snowflake_config["database"]}"')
        cursor.execute(f'CREATE SCHEMA "{snowflake_config["database"]}"."{snowflake_config["schema"]}"')
        cursor.execute(f'USE SCHEMA "{snowflake_config["database"]}"."{snowflake_config["schema"]}"')

        yield cursor

        cursor.execute(f'DROP DATABASE IF EXISTS "{snowflake_config["database"]}" CASCADE')


@pytest.fixture
def garbage_jsonl_file():
    """Manage a JSON file with garbage data."""
    with tempfile.NamedTemporaryFile("w+b", suffix=".jsonl", prefix="garbage_") as garbage_jsonl_file:
        garbage_jsonl_file.write(b'{"team_id": totally not an integer}\n')
        garbage_jsonl_file.seek(0)

        yield garbage_jsonl_file.name
