import os
import uuid

import pytest

import snowflake.connector

from products.batch_exports.backend.api.destination_tests.snowflake import (
    SnowflakeDatabaseTestStep,
    SnowflakeEstablishConnectionTestStep,
    SnowflakeSchemaTestStep,
    SnowflakeWarehouseTestStep,
    Status,
)
from products.batch_exports.backend.temporal.destinations.snowflake_batch_export import load_private_key

REQUIRED_ENV_VARS = (
    "SNOWFLAKE_WAREHOUSE",
    "SNOWFLAKE_ACCOUNT",
    "SNOWFLAKE_USERNAME",
)


def snowflake_env_vars_are_set():
    if not all(env_var in os.environ for env_var in REQUIRED_ENV_VARS):
        return False
    if "SNOWFLAKE_PASSWORD" not in os.environ and "SNOWFLAKE_PRIVATE_KEY" not in os.environ:
        return False
    return True


SKIP_IF_MISSING_REQUIRED_ENV_VARS = pytest.mark.skipif(
    not snowflake_env_vars_are_set(),
    reason="Snowflake required env vars are not set",
)

pytestmark = [SKIP_IF_MISSING_REQUIRED_ENV_VARS, pytest.mark.asyncio]


@pytest.fixture
def database():
    """Generate a unique database name for tests."""
    return f"test_batch_exports_{uuid.uuid4()}"


@pytest.fixture
def schema():
    """Generate a unique schema name for tests."""
    return f"test_batch_exports_{uuid.uuid4()}"


@pytest.fixture
def snowflake_config(database, schema) -> dict[str, str]:
    """Return a Snowflake configuration dictionary to use in tests.

    We set default configuration values to support tests against the Snowflake API
    and tests that mock it.
    """
    warehouse = os.getenv("SNOWFLAKE_WAREHOUSE", "warehouse")
    account = os.getenv("SNOWFLAKE_ACCOUNT", "account")
    role = os.getenv("SNOWFLAKE_ROLE", "role")
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
def snowflake_cursor(snowflake_config):
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
        role=f'"{snowflake_config["role"]}"' if snowflake_config["role"] is not None else None,
        account=snowflake_config["account"],
        warehouse=snowflake_config["warehouse"],
        private_key=private_key,
    ) as connection:
        cursor = connection.cursor()
        yield cursor

        cursor.execute(f'DROP DATABASE IF EXISTS "{snowflake_config["database"]}" CASCADE')


@pytest.fixture
def ensure_database(snowflake_cursor, snowflake_config):
    snowflake_cursor.execute(f'CREATE DATABASE "{snowflake_config["database"]}"')


@pytest.fixture
def ensure_schema(snowflake_cursor, snowflake_config):
    snowflake_cursor.execute(f'CREATE SCHEMA "{snowflake_config["database"]}"."{snowflake_config["schema"]}"')


async def test_snowflake_establish_connection_test_step(snowflake_config):
    test_step = SnowflakeEstablishConnectionTestStep(
        account=snowflake_config["account"],
        user=snowflake_config["user"],
        role=snowflake_config.get("role", None),
        password=snowflake_config.get("password", None),
        private_key=snowflake_config.get("private_key", None),
        private_key_passphrase=snowflake_config.get("private_key_passphrase", None),
    )
    result = await test_step.run()

    assert result.status == Status.PASSED
    assert result.message is None


async def test_snowflake_establish_connection_with_wrong_account(snowflake_config):
    test_step = SnowflakeEstablishConnectionTestStep(
        account="garbage",
        user=snowflake_config["user"],
        role=snowflake_config.get("role", None),
        password=snowflake_config.get("password", None),
        private_key=snowflake_config.get("private_key", None),
        private_key_passphrase=snowflake_config.get("private_key_passphrase", None),
    )
    result = await test_step.run()

    assert result.status == Status.FAILED
    assert (
        result.message
        == "Could not establish a connection to Snowflake as the resolved URL does not exist. This usually indicates an invalid Snowflake account."
    )


async def test_snowflake_establish_connection_with_wrong_user(snowflake_config):
    test_step = SnowflakeEstablishConnectionTestStep(
        account=snowflake_config["account"],
        user="garbage",
        role=snowflake_config.get("role", None),
        password=snowflake_config.get("password", None),
        private_key=snowflake_config.get("private_key", None),
        private_key_passphrase=snowflake_config.get("private_key_passphrase", None),
    )
    result = await test_step.run()

    assert result.status == Status.FAILED
    assert result.message is not None
    assert "Incorrect username or password was specified." in result.message


async def test_snowflake_establish_connection_with_invalid_private_key(snowflake_config):
    test_step = SnowflakeEstablishConnectionTestStep(
        account=snowflake_config["account"],
        user=snowflake_config["user"],
        role=snowflake_config.get("role", None),
        password=snowflake_config.get("password", None),
        private_key="garbage",
        private_key_passphrase=snowflake_config.get("private_key_passphrase", None),
    )
    result = await test_step.run()

    assert result.status == Status.FAILED
    assert result.message is not None
    assert "An error occurred when attempting to load configured private key:" in result.message


async def test_snowflake_warehouse_test_step(snowflake_config):
    test_step = SnowflakeWarehouseTestStep(
        account=snowflake_config["account"],
        user=snowflake_config["user"],
        role=snowflake_config.get("role", None),
        password=snowflake_config.get("password", None),
        private_key=snowflake_config.get("private_key", None),
        private_key_passphrase=snowflake_config.get("private_key_passphrase", None),
        warehouse=snowflake_config["warehouse"],
    )
    result = await test_step.run()

    assert result.status == Status.PASSED
    assert result.message is None


async def test_snowflake_warehouse_with_invalid_warehouse(snowflake_config):
    test_step = SnowflakeWarehouseTestStep(
        account=snowflake_config["account"],
        user=snowflake_config["user"],
        role=snowflake_config.get("role", None),
        password=snowflake_config.get("password", None),
        private_key=snowflake_config.get("private_key", None),
        private_key_passphrase=snowflake_config.get("private_key_passphrase", None),
        warehouse="garbage",
    )
    result = await test_step.run()

    assert result.status == Status.FAILED
    assert (
        result.message
        == "The configured warehouse 'garbage' does not exist or we are missing 'USAGE' permissions on it."
    )


async def test_snowflake_database_test_step(snowflake_config, ensure_database):
    test_step = SnowflakeDatabaseTestStep(
        account=snowflake_config["account"],
        user=snowflake_config["user"],
        role=snowflake_config.get("role", None),
        password=snowflake_config.get("password", None),
        private_key=snowflake_config.get("private_key", None),
        private_key_passphrase=snowflake_config.get("private_key_passphrase", None),
        warehouse=snowflake_config["warehouse"],
        database=snowflake_config["database"],
    )
    result = await test_step.run()

    assert result.status == Status.PASSED
    assert result.message is None


async def test_snowflake_database_with_invalid_database(snowflake_config):
    test_step = SnowflakeDatabaseTestStep(
        account=snowflake_config["account"],
        user=snowflake_config["user"],
        role=snowflake_config.get("role", None),
        password=snowflake_config.get("password", None),
        private_key=snowflake_config.get("private_key", None),
        private_key_passphrase=snowflake_config.get("private_key_passphrase", None),
        warehouse=snowflake_config["warehouse"],
        database="garbage",
    )
    result = await test_step.run()

    assert result.status == Status.FAILED
    assert (
        result.message
        == "The configured database 'garbage' does not exist or we are missing 'USAGE' permissions on it."
    )


async def test_snowflake_schema_test_step(snowflake_config, ensure_database, ensure_schema):
    test_step = SnowflakeSchemaTestStep(
        account=snowflake_config["account"],
        user=snowflake_config["user"],
        role=snowflake_config.get("role", None),
        password=snowflake_config.get("password", None),
        private_key=snowflake_config.get("private_key", None),
        private_key_passphrase=snowflake_config.get("private_key_passphrase", None),
        warehouse=snowflake_config["warehouse"],
        database=snowflake_config["database"],
        schema=snowflake_config["schema"],
    )
    result = await test_step.run()

    assert result.status == Status.PASSED
    assert result.message is None


async def test_snowflake_schema_with_invalid_schema(snowflake_config, ensure_database):
    test_step = SnowflakeSchemaTestStep(
        account=snowflake_config["account"],
        user=snowflake_config["user"],
        role=snowflake_config.get("role", None),
        password=snowflake_config.get("password", None),
        private_key=snowflake_config.get("private_key", None),
        private_key_passphrase=snowflake_config.get("private_key_passphrase", None),
        warehouse=snowflake_config["warehouse"],
        database=snowflake_config["database"],
        schema="garbage",
    )
    result = await test_step.run()

    assert result.status == Status.FAILED
    assert (
        result.message == "The configured schema 'garbage' does not exist or we are missing 'USAGE' permissions on it."
    )


@pytest.fixture
def password():
    return str(uuid.uuid4())


@pytest.fixture
def user(snowflake_cursor, password):
    """Manage a test user without any privileges."""
    test_user = "EMPTY_TEST_USER"
    snowflake_cursor.execute(f"DROP USER IF EXISTS {test_user}")

    snowflake_cursor.execute(f"CREATE USER {test_user} PASSWORD = '{password}'")

    yield test_user

    snowflake_cursor.execute(f"DROP USER {test_user}")


@pytest.fixture
def role(snowflake_cursor, snowflake_config, user, ensure_database):
    """Manage a test role without any privileges."""
    test_role = "EMPTY_TEST_ROLE"
    snowflake_cursor.execute(f"DROP ROLE IF EXISTS {test_role}")

    snowflake_cursor.execute(f"CREATE ROLE {test_role}")
    snowflake_cursor.execute(f"GRANT ROLE {test_role} TO USER {user}")

    yield test_role

    snowflake_cursor.execute(f"DROP ROLE {test_role}")


async def test_snowflake_schema_without_permissions(
    snowflake_config, snowflake_cursor, user, password, role, ensure_database, ensure_schema
):
    """Test whether a Snowflake schema test fails without permissions."""
    # Grant database USAGE privilege otherwise we will fail before checking schema.
    snowflake_cursor.execute(f"GRANT USAGE ON DATABASE \"{snowflake_config['database']}\" TO ROLE {role}")

    test_step = SnowflakeSchemaTestStep(
        account=snowflake_config["account"],
        user=user,
        role=role,
        password=password,
        warehouse=snowflake_config["warehouse"],
        database=snowflake_config["database"],
        schema=snowflake_config["schema"],
    )
    result = await test_step.run()

    assert result.status == Status.FAILED
    assert (
        result.message
        == f"The configured schema '{snowflake_config['schema']}' does not exist or we are missing 'USAGE' permissions on it."
    )


@pytest.mark.parametrize(
    "step",
    [
        SnowflakeEstablishConnectionTestStep(),
        SnowflakeWarehouseTestStep(),
        SnowflakeDatabaseTestStep(),
        SnowflakeSchemaTestStep(),
    ],
)
async def test_test_steps_fail_if_not_configured(step):
    result = await step.run()
    assert result.status == Status.FAILED
    assert result.message == "The test step cannot run as it's not configured."
